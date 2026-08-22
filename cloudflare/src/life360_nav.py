from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

LIFE360_COMMON_SHARES = 37_028
LIFE360_FAIR_VALUE_POLICY_START = "2025-12-31"
LIFE360_HISTORY_START = "2019-05-10"
MAX_MARKET_LOOKBACK_DAYS = 7
MAX_FX_LOOKBACK_DAYS = 7


async def _lif_price(repository, as_of_date: str) -> dict[str, Any] | None:
    floor = (date.fromisoformat(as_of_date) - timedelta(days=MAX_MARKET_LOOKBACK_DAYS)).isoformat()
    return await repository.first(
        """
        SELECT mp.trading_date, mp.observed_at, mp.price, mp.quality,
               mp.source_document_id, s.code AS source_code
        FROM market_prices mp
        JOIN instruments i ON i.id=mp.instrument_id
        JOIN sources s ON s.id=mp.source_id
        WHERE i.symbol='LIF' AND mp.currency='USD'
          AND mp.price_type IN ('CLOSE','LAST')
          AND mp.trading_date <= ? AND mp.trading_date >= ?
        ORDER BY mp.trading_date DESC,
                 CASE s.code WHEN 'YAHOO_FINANCE' THEN 0 ELSE 5 END,
                 CASE mp.price_type WHEN 'CLOSE' THEN 0 ELSE 1 END,
                 mp.observed_at DESC, mp.id DESC
        LIMIT 1
        """,
        (as_of_date, floor),
    )


async def _usd_nok(repository, as_of_date: str) -> dict[str, Any] | None:
    floor = (date.fromisoformat(as_of_date) - timedelta(days=MAX_FX_LOOKBACK_DAYS)).isoformat()
    return await repository.first(
        """
        SELECT substr(fr.observed_at,1,10) AS rate_date, fr.rate,
               fr.source_document_id, s.code AS source_code
        FROM fx_rates fr
        JOIN sources s ON s.id=fr.source_id
        WHERE fr.base_currency='USD' AND fr.quote_currency='NOK'
          AND substr(fr.observed_at,1,10) <= ?
          AND substr(fr.observed_at,1,10) >= ?
        ORDER BY substr(fr.observed_at,1,10) DESC,
                 CASE s.code WHEN 'NORGES_BANK' THEN 0 WHEN 'ECB' THEN 1 ELSE 5 END,
                 fr.observed_at DESC, fr.id DESC
        LIMIT 1
        """,
        (as_of_date, floor),
    )


async def _report_anchor_date(repository, as_of_date: str) -> str | None:
    row = await repository.first(
        """
        SELECT r.as_of_date
        FROM other_net_assets_reported_anchors r
        JOIN other_net_assets_anchors n ON n.reported_anchor_id=r.id
        WHERE r.as_of_date <= ? AND r.as_of_date >= ?
        ORDER BY r.as_of_date DESC, r.id DESC
        LIMIT 1
        """,
        (as_of_date, LIFE360_FAIR_VALUE_POLICY_START),
    )
    return None if row is None else str(row["as_of_date"])


async def life360_nav_adjustment(repository, *, as_of_date: str) -> dict[str, Any]:
    """Replace the Life360 value embedded in reported ONA with current market value.

    From the 2025 annual accounts Life360 is fair-valued. The daily ONA model carries the
    latest report anchor in USD between reports, so the embedded Life360 amount is modeled
    as the LIF USD market value at the latest ONA report date translated with the current
    USD/NOK rate. The investor adjustment is therefore current LIF market value minus that
    embedded report-anchor value. Accounting FULL NAV itself is never rewritten.
    """
    if as_of_date < LIFE360_FAIR_VALUE_POLICY_START:
        return {
            "ready": False,
            "reason": "life360_fair_value_policy_not_active",
            "as_of_date": as_of_date,
            "shares": LIFE360_COMMON_SHARES,
            "history_available_from": LIFE360_HISTORY_START,
            "adjustment_nok": Decimal("0"),
        }

    anchor_date = await _report_anchor_date(repository, as_of_date)
    if anchor_date is None:
        return {
            "ready": False,
            "reason": "missing_life360_report_anchor",
            "as_of_date": as_of_date,
            "shares": LIFE360_COMMON_SHARES,
            "history_available_from": LIFE360_HISTORY_START,
            "adjustment_nok": Decimal("0"),
        }

    current_price = await _lif_price(repository, as_of_date)
    anchor_price = await _lif_price(repository, anchor_date)
    usd_nok = await _usd_nok(repository, as_of_date)
    if current_price is None or anchor_price is None or usd_nok is None:
        missing = []
        if current_price is None:
            missing.append("current_lif_price")
        if anchor_price is None:
            missing.append("anchor_lif_price")
        if usd_nok is None:
            missing.append("usd_nok")
        return {
            "ready": False,
            "reason": "missing_" + "_and_".join(missing),
            "as_of_date": as_of_date,
            "anchor_date": anchor_date,
            "shares": LIFE360_COMMON_SHARES,
            "history_available_from": LIFE360_HISTORY_START,
            "adjustment_nok": Decimal("0"),
        }

    shares = Decimal(LIFE360_COMMON_SHARES)
    current_price_usd = Decimal(str(current_price["price"]))
    anchor_price_usd = Decimal(str(anchor_price["price"]))
    fx = Decimal(str(usd_nok["rate"]))
    current_value_usd = shares * current_price_usd
    embedded_value_usd = shares * anchor_price_usd
    current_value_nok = current_value_usd * fx
    embedded_value_nok = embedded_value_usd * fx
    adjustment_nok = current_value_nok - embedded_value_nok
    price_date = str(current_price["trading_date"])
    price_age_days = max(0, (date.fromisoformat(as_of_date) - date.fromisoformat(price_date)).days)

    return {
        "ready": True,
        "quality": "MARK_TO_MARKET_SECONDARY",
        "as_of_date": as_of_date,
        "shares": LIFE360_COMMON_SHARES,
        "holding_basis": "DERIVED_HIGH_CONFIDENCE_2025_FAIR_VALUE",
        "history_available_from": LIFE360_HISTORY_START,
        "market_symbol": "LIF",
        "currency": "USD",
        "price": current_price_usd,
        "price_date": price_date,
        "price_age_days": price_age_days,
        "price_source": str(current_price.get("source_code") or ""),
        "price_quality": str(current_price.get("quality") or ""),
        "price_source_document_id": current_price.get("source_document_id"),
        "fx_rate": fx,
        "fx_date": str(usd_nok["rate_date"]),
        "fx_source": str(usd_nok.get("source_code") or ""),
        "fx_source_document_id": usd_nok.get("source_document_id"),
        "anchor_date": anchor_date,
        "anchor_price_usd": anchor_price_usd,
        "anchor_price_date": str(anchor_price["trading_date"]),
        "anchor_price_source_document_id": anchor_price.get("source_document_id"),
        "market_value_usd": current_value_usd,
        "market_value_nok": current_value_nok,
        "embedded_value_usd": embedded_value_usd,
        "embedded_value_nok": embedded_value_nok,
        "adjustment_nok": adjustment_nok,
        "stale": price_age_days > MAX_MARKET_LOOKBACK_DAYS,
        "method": "CURRENT_LIF_MINUS_REPORTED_LIF_FAIR_VALUE_IN_CARRIED_USD_ONA",
        "note": (
            "Investor-NAV erstatter Life360-verdien som ligger inne i siste rapporterte ONA-anker "
            "med markedsverdien av 37 028 LIF-aksjer. Regnskapsmessig FULL NAV endres ikke."
        ),
    }

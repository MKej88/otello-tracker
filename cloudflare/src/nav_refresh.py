from __future__ import annotations

import hashlib
import json
import re
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

try:
    from .option_liability import OPTION_PROGRAM, decimal_text, option_liability_for_day
except ImportError:
    from option_liability import OPTION_PROGRAM, decimal_text, option_liability_for_day

CORE_CALCULATION_VERSION = "core-market-nav-daily-v1"
FULL_CALCULATION_VERSION = "full-market-nav-daily-v2"
MAX_LOOKBACK_DAYS = 7
_BUYBACK_PERIOD_RE = re.compile(r"during\s+(20\d{2}-\d{2}-\d{2})[–-](20\d{2}-\d{2}-\d{2})", re.I)


def _hash(payload: Any) -> str:
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def _nearest_fx(repository, base: str, as_of_date: str) -> dict[str, Any] | None:
    floor_date = (date.fromisoformat(as_of_date) - timedelta(days=MAX_LOOKBACK_DAYS)).isoformat()
    return await repository.first(
        """
        SELECT fr.id, substr(fr.observed_at, 1, 10) AS rate_date, fr.rate,
               fr.source_document_id
        FROM fx_rates fr
        JOIN sources s ON s.id=fr.source_id
        WHERE fr.base_currency=? AND fr.quote_currency='NOK'
          AND substr(fr.observed_at,1,10) <= ? AND substr(fr.observed_at,1,10) >= ?
        ORDER BY substr(fr.observed_at,1,10) DESC,
                 CASE s.code
                   WHEN 'NORGES_BANK' THEN 0
                   WHEN 'ECB' THEN 1
                   ELSE 5
                 END,
                 fr.observed_at DESC,
                 fr.id DESC
        LIMIT 1
        """,
        (base, as_of_date, floor_date),
    )


async def _preferred_price(repository, symbol: str, as_of_date: str) -> dict[str, Any] | None:
    floor_date = (date.fromisoformat(as_of_date) - timedelta(days=MAX_LOOKBACK_DAYS)).isoformat()
    return await repository.first(
        """
        SELECT mp.id, mp.trading_date, mp.observed_at, mp.price_type,
               mp.price, mp.quality, mp.source_document_id,
               s.code AS source_code
        FROM market_prices mp
        JOIN instruments i ON i.id = mp.instrument_id
        JOIN sources s ON s.id = mp.source_id
        WHERE i.symbol = ? AND mp.price_type IN ('CLOSE', 'LAST')
          AND mp.trading_date <= ? AND mp.trading_date >= ?
        ORDER BY mp.trading_date DESC,
                 CASE s.code
                   WHEN 'EURONEXT' THEN 0
                   WHEN 'B3' THEN 0
                   WHEN 'INVESTING' THEN 2
                   ELSE 5
                 END,
                 CASE mp.price_type
                   WHEN 'CLOSE' THEN 0
                   WHEN 'LAST' THEN 1
                   ELSE 5
                 END,
                 CASE mp.quality WHEN 'DIRECT' THEN 0 ELSE 1 END,
                 mp.observed_at DESC,
                 mp.id DESC
        LIMIT 1
        """,
        (symbol, as_of_date, floor_date),
    )


async def _holding(repository, as_of_date: str) -> dict[str, Any] | None:
    return await repository.first(
        """
        SELECT id, shares, ownership_pct, effective_from, effective_to
        FROM bemobi_holdings
        WHERE effective_from <= ? AND (effective_to IS NULL OR effective_to >= ?)
        ORDER BY effective_from DESC, id DESC LIMIT 1
        """,
        (as_of_date, as_of_date),
    )


async def _share_count(repository, as_of_date: str) -> dict[str, Any] | None:
    return await repository.first(
        """
        SELECT id, effective_from, total_shares, treasury_shares, outstanding_shares
        FROM otello_share_counts
        WHERE effective_from <= ?
        ORDER BY effective_from DESC, id DESC LIMIT 1
        """,
        (as_of_date,),
    )


async def _share_count_may_be_stale(repository, as_of_date: str, share_count_date: str) -> bool:
    latest = await repository.first(
        """
        SELECT b.trade_date, b.cumulative_program_shares, p.max_shares
        FROM buybacks b
        LEFT JOIN buyback_programs p ON p.id = b.program_id
        WHERE b.trade_date <= ?
        ORDER BY b.trade_date DESC, b.id DESC
        LIMIT 1
        """,
        (as_of_date,),
    )
    if latest is None:
        return False
    if share_count_date < latest["trade_date"]:
        return True
    if share_count_date > latest["trade_date"] or as_of_date == share_count_date:
        return False
    max_shares = latest.get("max_shares")
    cumulative = latest.get("cumulative_program_shares")
    if max_shares is None or cumulative is None or int(cumulative) >= int(max_shares):
        return False
    age = (date.fromisoformat(as_of_date) - date.fromisoformat(str(latest["trade_date"]))).days
    return 0 < age <= 14


async def _latest_nav_date(repository, target_date: str) -> tuple[str | None, bool]:
    exact = await repository.first(
        """
        SELECT 1 AS found
        FROM market_prices mp
        JOIN instruments i ON i.id=mp.instrument_id
        WHERE i.symbol IN ('OTEC','BMOB3')
          AND mp.price_type IN ('CLOSE','LAST')
          AND mp.trading_date=?
        LIMIT 1
        """,
        (target_date,),
    )
    if exact is not None:
        return target_date, True
    latest = await repository.first(
        """
        SELECT MAX(mp.trading_date) AS d
        FROM market_prices mp
        JOIN instruments i ON i.id=mp.instrument_id
        WHERE i.symbol='OTEC' AND mp.price_type IN ('CLOSE','LAST')
          AND mp.trading_date <= ?
        """,
        (target_date,),
    )
    return (str(latest["d"]) if latest and latest.get("d") else None), False


async def refresh_daily_cash_if_dirty(repository, as_of_date: str) -> dict[str, Any]:
    """Refresh one post-anchor cash estimate only when its deterministic inputs changed."""
    anchor = await repository.first(
        """
        SELECT id, as_of_date, amount_nok, reported_amount, reported_currency,
               source_document_id, notes
        FROM cash_anchors
        WHERE anchor_type='REPORTED' AND as_of_date <= ?
        ORDER BY as_of_date DESC, id DESC LIMIT 1
        """,
        (as_of_date,),
    )
    if anchor is None:
        return {"status": "not_ready", "reason": "missing_reported_cash_anchor", "date": as_of_date}

    currency = str(anchor.get("reported_currency") or "NOK")
    if anchor.get("reported_amount") is not None:
        reported = Decimal(str(anchor["reported_amount"]))
        if currency == "NOK":
            fx_rate = Decimal("1")
            fx_id = None
            fx_date = anchor["as_of_date"]
        else:
            fx = await _nearest_fx(repository, currency, str(anchor["as_of_date"]))
            if fx is None:
                return {
                    "status": "not_ready",
                    "reason": f"missing_{currency.lower()}_nok_for_cash_anchor",
                    "date": as_of_date,
                }
            fx_rate = Decimal(str(fx["rate"]))
            fx_id = fx["id"]
            fx_date = fx["rate_date"]
        anchor_cash = reported * fx_rate
    elif anchor.get("amount_nok") is not None:
        anchor_cash = Decimal(str(anchor["amount_nok"]))
        fx_rate = Decimal("1")
        fx_id = None
        fx_date = anchor["as_of_date"]
    else:
        return {"status": "not_ready", "reason": "cash_anchor_has_no_amount", "date": as_of_date}

    movements = await repository.all(
        """
        SELECT id, movement_date, movement_type, amount_nok, confidence,
               corporate_action_id, source_document_id, description
        FROM cash_movements
        WHERE movement_date > ? AND movement_date <= ?
        ORDER BY movement_date, id
        """,
        (anchor["as_of_date"], as_of_date),
    )
    modeled: list[dict[str, Any]] = []
    cumulative = Decimal("0")
    cross_anchor_exclusions = 0
    for raw in movements:
        item = dict(raw)
        model_amount = Decimal(str(item["amount_nok"]))
        timing_quality = "DIRECT_DATE"
        if item["movement_type"] == "OTELLO_BUYBACK":
            match = _BUYBACK_PERIOD_RE.search(str(item.get("description") or ""))
            if match:
                period_start, period_end = match.groups()
                item["period_start"] = period_start
                item["period_end"] = period_end
                if period_start <= str(anchor["as_of_date"]) < str(item["movement_date"]):
                    model_amount = Decimal("0")
                    timing_quality = "CROSS_ANCHOR_EXCLUDED"
                    cross_anchor_exclusions += 1
        item["model_amount_nok"] = decimal_text(model_amount)
        item["timing_quality"] = timing_quality
        cumulative += model_amount
        modeled.append(item)

    cash_nok = anchor_cash + cumulative
    quality = "REPORTED" if as_of_date == anchor["as_of_date"] else "FORECAST_PARTIAL"
    payload = {
        "last_reported_anchor": {
            "id": anchor["id"],
            "date": anchor["as_of_date"],
            "reported_amount": anchor.get("reported_amount"),
            "currency": currency,
            "fx_rate": decimal_text(fx_rate),
            "fx_id": fx_id,
            "fx_date": fx_date,
            "cash_nok": decimal_text(anchor_cash),
            "source_document_id": anchor["source_document_id"],
        },
        "date": as_of_date,
        "movements": modeled,
        "known_movements_nok": decimal_text(cumulative),
        "method": "known-flows-only-forecast-v2-cross-anchor-safe",
    }
    inputs_hash = _hash(payload)
    existing = await repository.first(
        "SELECT cash_nok, quality, inputs_hash FROM cash_daily_estimates WHERE estimate_date=?",
        (as_of_date,),
    )
    if (
        existing is not None
        and str(existing.get("inputs_hash")) == inputs_hash
        and str(existing.get("cash_nok")) == decimal_text(cash_nok)
        and str(existing.get("quality")) == quality
    ):
        return {
            "status": "ok",
            "date": as_of_date,
            "dirty": False,
            "skipped": True,
            "reason": "cash_inputs_unchanged",
            "cash_nok": decimal_text(cash_nok),
            "inputs_hash": inputs_hash,
        }

    notes = (
        "Reported anchor" if quality == "REPORTED" else
        "Partial forecast from last reported cash anchor using known corporate-action flows only. "
        "Weekly buybacks that straddle the anchor are excluded rather than double-counted; "
        "operating costs and unseeded flows are not accrued."
    )
    await repository.run(
        """
        INSERT INTO cash_daily_estimates(
            estimate_date, cash_nok, period_start_date, period_end_date,
            cumulative_known_movements_nok, cumulative_residual_nok,
            quality, inputs_hash, notes
        ) VALUES (?, ?, ?, NULL, ?, '0', ?, ?, ?)
        ON CONFLICT(estimate_date) DO UPDATE SET
            cash_nok=excluded.cash_nok,
            period_start_date=excluded.period_start_date,
            period_end_date=NULL,
            cumulative_known_movements_nok=excluded.cumulative_known_movements_nok,
            cumulative_residual_nok='0',
            quality=excluded.quality,
            inputs_hash=excluded.inputs_hash,
            notes=excluded.notes
        """,
        (
            as_of_date,
            decimal_text(cash_nok),
            anchor["as_of_date"],
            decimal_text(cumulative),
            quality,
            inputs_hash,
            notes,
        ),
    )
    return {
        "status": "ok",
        "date": as_of_date,
        "dirty": True,
        "skipped": False,
        "cash_nok": decimal_text(cash_nok),
        "known_movements_nok": decimal_text(cumulative),
        "movement_count": len(movements),
        "cross_anchor_buybacks_excluded": cross_anchor_exclusions,
        "inputs_hash": inputs_hash,
    }


async def _cash_for_date(repository, as_of_date: str) -> dict[str, Any] | None:
    return await repository.first(
        """
        SELECT c.id, c.estimate_date, c.cash_nok, c.quality, c.inputs_hash,
               c.period_start_date, c.period_end_date,
               p.quality AS calibration_quality
        FROM cash_daily_estimates c
        LEFT JOIN cash_period_calibrations p
          ON p.start_anchor_date = c.period_start_date
         AND p.end_anchor_date = c.period_end_date
        WHERE c.estimate_date=?
        """,
        (as_of_date,),
    )


async def calculate_core_nav(repository, as_of_date: str) -> dict[str, Any]:
    bmob3 = await _preferred_price(repository, "BMOB3", as_of_date)
    otec = await _preferred_price(repository, "OTEC", as_of_date)
    brl_nok = await _nearest_fx(repository, "BRL", as_of_date)
    holding = await _holding(repository, as_of_date)
    shares = await _share_count(repository, as_of_date)
    cash = await _cash_for_date(repository, as_of_date)
    required = {
        "BMOB3 market price": bmob3,
        "OTEC market price": otec,
        "BRL/NOK": brl_nok,
        "Bemobi holding": holding,
        "OTEC share count": shares,
        "daily cash": cash,
    }
    missing = [name for name, value in required.items() if value is None]
    if missing:
        return {"as_of_date": as_of_date, "ready": False, "missing": missing}

    assert bmob3 and otec and brl_nok and holding and shares and cash
    bmob3_price = Decimal(str(bmob3["price"]))
    brl_rate = Decimal(str(brl_nok["rate"]))
    otec_price = Decimal(str(otec["price"]))
    cash_nok = Decimal(str(cash["cash_nok"]))
    holding_shares = int(holding["shares"])
    outstanding = int(shares["outstanding_shares"])
    bemobi_value = bmob3_price * Decimal(holding_shares) * brl_rate
    nav_total = bemobi_value + cash_nok
    nav_per_share = nav_total / Decimal(outstanding)
    discount = (Decimal("1") - otec_price / nav_per_share) * Decimal("100")

    stale_share_count = await _share_count_may_be_stale(
        repository, as_of_date, str(shares["effective_from"])
    )
    high_residual = cash.get("calibration_quality") == "HIGH_RESIDUAL"
    forecast_partial = cash.get("quality") == "FORECAST_PARTIAL"
    if forecast_partial or high_residual or stale_share_count:
        status = "DEGRADED"
    elif cash.get("quality") == "ANCHORED_ESTIMATE":
        status = "ESTIMATED"
    else:
        status = "BACKFILLED"

    notes = (
        "CORE daily NAV uses Bemobi market value plus anchored/estimated cash. "
        "Other net assets/liabilities are excluded."
    )
    if otec["price_type"] == "LAST":
        notes += " OTEC uses Euronext's delayed latest reported trade, not an official closing price."
    if forecast_partial:
        notes += " Cash is a partial post-anchor forecast using known corporate-action flows only."
    if high_residual:
        notes += " Cash sits inside a high-residual anchor period; daily interpolation is lower quality."
    if stale_share_count:
        notes += " OTEC outstanding-share count can be stale because a recent buyback program still has unused authorization after the latest weekly share-count status."

    components = {
        "scope": "CORE",
        "as_of_date": as_of_date,
        "bmob3": {
            "price_id": bmob3["id"],
            "price_date": bmob3["trading_date"],
            "price_observed_at": bmob3["observed_at"],
            "price_type": bmob3["price_type"],
            "price_brl": bmob3["price"],
            "price_source": bmob3["source_code"],
            "price_quality": bmob3["quality"],
            "holding_id": holding["id"],
            "holding_shares": holding_shares,
            "brl_nok_id": brl_nok["id"],
            "brl_nok_date": brl_nok["rate_date"],
            "brl_nok": brl_nok["rate"],
        },
        "otec": {
            "price_id": otec["id"],
            "price_date": otec["trading_date"],
            "price_observed_at": otec["observed_at"],
            "price_type": otec["price_type"],
            "price_nok": otec["price"],
            "price_source": otec["source_code"],
            "price_quality": otec["quality"],
            "share_count_id": shares["id"],
            "share_count_date": shares["effective_from"],
            "outstanding_shares": outstanding,
            "share_count_quality": "POTENTIALLY_STALE" if stale_share_count else "CURRENT_KNOWN",
        },
        "cash": {
            "daily_cash_id": cash["id"],
            "cash_nok": cash["cash_nok"],
            "quality": cash["quality"],
            "calibration_quality": cash.get("calibration_quality"),
            "inputs_hash": cash["inputs_hash"],
        },
    }
    return {
        "as_of_date": as_of_date,
        "ready": True,
        "nav_total_nok": nav_total,
        "nav_per_share_nok": nav_per_share,
        "otec_price_nok": otec_price,
        "discount_pct": discount,
        "bemobi_value_nok": bemobi_value,
        "cash_nok": cash_nok,
        "other_net_assets_nok": Decimal("0"),
        "shares_outstanding": outstanding,
        "status": status,
        "components": components,
        "inputs_hash": _hash(components),
        "quality_notes": notes,
    }


async def refresh_core_nav_if_dirty(repository, as_of_date: str) -> dict[str, Any]:
    result = await calculate_core_nav(repository, as_of_date)
    if not result["ready"]:
        return {"status": "not_ready", "date": as_of_date, "missing": result["missing"]}
    as_of_at = f"{as_of_date}T23:59:59Z"
    existing = await repository.first(
        """
        SELECT id, inputs_hash FROM nav_snapshots
        WHERE as_of_at=? AND calculation_version=? AND nav_scope='CORE'
        LIMIT 1
        """,
        (as_of_at, CORE_CALCULATION_VERSION),
    )
    if existing is not None and str(existing.get("inputs_hash")) == result["inputs_hash"]:
        return {
            "status": "ok",
            "date": as_of_date,
            "dirty": False,
            "skipped": True,
            "reason": "core_inputs_unchanged",
            "snapshot_id": int(existing["id"]),
            "inputs_hash": result["inputs_hash"],
        }

    await repository.run(
        """
        INSERT INTO nav_snapshots(
            as_of_at, nav_total_nok, nav_per_share_nok, otec_price_nok,
            discount_pct, bemobi_value_nok, cash_estimate_nok,
            other_net_assets_nok, shares_outstanding, calculation_version,
            inputs_hash, status, nav_scope, components_json, quality_notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'CORE', ?, ?)
        ON CONFLICT(as_of_at, calculation_version) DO UPDATE SET
            nav_total_nok=excluded.nav_total_nok,
            nav_per_share_nok=excluded.nav_per_share_nok,
            otec_price_nok=excluded.otec_price_nok,
            discount_pct=excluded.discount_pct,
            bemobi_value_nok=excluded.bemobi_value_nok,
            cash_estimate_nok=excluded.cash_estimate_nok,
            other_net_assets_nok=excluded.other_net_assets_nok,
            shares_outstanding=excluded.shares_outstanding,
            inputs_hash=excluded.inputs_hash,
            status=excluded.status,
            nav_scope=excluded.nav_scope,
            components_json=excluded.components_json,
            quality_notes=excluded.quality_notes
        """,
        (
            as_of_at,
            decimal_text(result["nav_total_nok"]),
            decimal_text(result["nav_per_share_nok"]),
            decimal_text(result["otec_price_nok"]),
            decimal_text(result["discount_pct"]),
            decimal_text(result["bemobi_value_nok"]),
            decimal_text(result["cash_nok"]),
            "0",
            result["shares_outstanding"],
            CORE_CALCULATION_VERSION,
            result["inputs_hash"],
            result["status"],
            json.dumps(result["components"], sort_keys=True, ensure_ascii=False),
            result["quality_notes"],
        ),
    )
    row = await repository.first(
        "SELECT id FROM nav_snapshots WHERE as_of_at=? AND calculation_version=? LIMIT 1",
        (as_of_at, CORE_CALCULATION_VERSION),
    )
    return {
        "status": "ok",
        "date": as_of_date,
        "dirty": True,
        "skipped": False,
        "snapshot_id": int(row["id"]) if row else None,
        "inputs_hash": result["inputs_hash"],
        "nav_per_share_nok": decimal_text(result["nav_per_share_nok"]),
    }


async def _reported_ona_anchors(repository) -> list[dict[str, Any]]:
    return await repository.all(
        """
        SELECT r.id, r.as_of_date, r.other_net_assets_reported,
               r.associated_receivable_reported, r.base_other_net_assets_reported,
               r.option_liability_reported, r.base_other_net_assets_ex_option_reported
        FROM other_net_assets_reported_anchors r
        JOIN other_net_assets_anchors n ON n.reported_anchor_id=r.id
        ORDER BY r.as_of_date, r.id
        """
    )


def _legacy_base(anchor: dict[str, Any]) -> Decimal:
    return Decimal(str(anchor["base_other_net_assets_reported"]))


def _anchor_base_ex_option(anchor: dict[str, Any]) -> Decimal:
    raw = anchor.get("base_other_net_assets_ex_option_reported")
    if raw is not None:
        return Decimal(str(raw))
    return _legacy_base(anchor) + Decimal(str(anchor.get("option_liability_reported") or "0"))


def _interpolated_base_ex_option(
    start_anchor: dict[str, Any],
    end_anchor: dict[str, Any],
    start_day: date,
    end_day: date,
    current: date,
) -> Decimal:
    legacy_start = _legacy_base(start_anchor)
    legacy_end = _legacy_base(end_anchor)
    elapsed = Decimal((current - start_day).days)
    span = Decimal((end_day - start_day).days)
    legacy_current = legacy_start + (legacy_end - legacy_start) * elapsed / span
    grant = date.fromisoformat(OPTION_PROGRAM["program"]["grant_date"])

    # Når begge rapportankrene er etter opsjonsgrantet, er opsjonsforpliktelsen
    # allerede skilt ut ved begge endepunktene. Interpoler derfor mellom de
    # dekomponerte ONA-verdiene. Ellers blir opsjonsforpliktelsen i praksis
    # trukket fra to ganger mellom rapportdatoene.
    if grant <= start_day:
        decomposed_start = _anchor_base_ex_option(start_anchor)
        decomposed_end = _anchor_base_ex_option(end_anchor)
        return decomposed_start + (decomposed_end - decomposed_start) * elapsed / span

    end_option = Decimal(str(end_anchor.get("option_liability_reported") or "0"))
    if end_option == 0:
        return legacy_current
    if not (start_day < grant <= end_day) or current < grant:
        return legacy_current
    grant_fraction = Decimal((grant - start_day).days) / span
    legacy_at_grant = legacy_start + (legacy_end - legacy_start) * grant_fraction
    if current == grant:
        return legacy_at_grant
    post_elapsed = Decimal((current - grant).days)
    post_span = Decimal((end_day - grant).days)
    return legacy_at_grant + (_anchor_base_ex_option(end_anchor) - legacy_at_grant) * post_elapsed / post_span


async def _receivable_actions(repository) -> list[dict[str, Any]]:
    actions = await repository.all(
        """
        SELECT ca.id, ca.action_type, ca.ex_date, ca.payment_date,
               ca.amount_per_share, ca.currency, ca.source_document_id,
               ca.component_group
        FROM corporate_actions ca
        JOIN instruments i ON i.id=ca.issuer_instrument_id
        WHERE i.symbol='BMOB3'
          AND ca.action_type IN ('DIVIDEND','JCP')
          AND ca.ex_date IS NOT NULL AND ca.payment_date IS NOT NULL
          AND ca.amount_per_share IS NOT NULL AND ca.currency='BRL'
        ORDER BY ca.ex_date, ca.id
        """
    )
    prepared: list[dict[str, Any]] = []
    gross_by_anchor: dict[int, Decimal] = {}
    for action in actions:
        holding = await _holding(repository, str(action["ex_date"]))
        if holding is None:
            continue
        gross_brl = Decimal(str(action["amount_per_share"])) * Decimal(int(holding["shares"]))
        calibration_anchor = await repository.first(
            """
            SELECT id, as_of_date, associated_receivable_reported
            FROM other_net_assets_reported_anchors
            WHERE as_of_date >= ? AND as_of_date < ?
              AND CAST(associated_receivable_reported AS REAL) != 0
            ORDER BY as_of_date LIMIT 1
            """,
            (action["ex_date"], action["payment_date"]),
        )
        if calibration_anchor is not None:
            anchor_id = int(calibration_anchor["id"])
            gross_by_anchor[anchor_id] = gross_by_anchor.get(anchor_id, Decimal("0")) + gross_brl
        prepared.append(
            {
                "action": action,
                "holding": holding,
                "gross_brl": gross_brl,
                "calibration_anchor": calibration_anchor,
            }
        )

    calibration_by_anchor: dict[int, dict[str, Any]] = {}
    for item in prepared:
        anchor = item["calibration_anchor"]
        if anchor is None:
            continue
        anchor_id = int(anchor["id"])
        if anchor_id in calibration_by_anchor:
            continue
        usd_fx = await _nearest_fx(repository, "USD", str(anchor["as_of_date"]))
        brl_fx = await _nearest_fx(repository, "BRL", str(anchor["as_of_date"]))
        total_gross_brl = gross_by_anchor[anchor_id]
        if usd_fx is None or brl_fx is None or total_gross_brl == 0:
            continue
        reported_usd = Decimal(str(anchor["associated_receivable_reported"]))
        reported_nok = reported_usd * Decimal(str(usd_fx["rate"]))
        gross_nok = total_gross_brl * Decimal(str(brl_fx["rate"]))
        if gross_nok == 0:
            continue
        calibration_by_anchor[anchor_id] = {
            "factor": reported_nok / gross_nok,
            "metadata": {
                "anchor_id": anchor_id,
                "anchor_date": anchor["as_of_date"],
                "reported_receivable_usd": decimal_text(reported_usd),
                "combined_gross_brl": decimal_text(total_gross_brl),
                "usd_nok": usd_fx["rate"],
                "brl_nok": brl_fx["rate"],
            },
        }

    result: list[dict[str, Any]] = []
    for item in prepared:
        action = item["action"]
        holding = item["holding"]
        gross_brl = item["gross_brl"]
        anchor = item["calibration_anchor"]
        factor = Decimal("1")
        quality = "ESTIMATED_GROSS"
        calibration = None
        if anchor is not None:
            calibrated = calibration_by_anchor.get(int(anchor["id"]))
            if calibrated is not None:
                factor = calibrated["factor"]
                quality = "REPORTED_CALIBRATED"
                calibration = calibrated["metadata"]
        result.append(
            {
                "id": action["id"],
                "action_type": action["action_type"],
                "ex_date": action["ex_date"],
                "payment_date": action["payment_date"],
                "amount_per_share": action["amount_per_share"],
                "component_group": action["component_group"],
                "holding_id": holding["id"],
                "holding_shares": int(holding["shares"]),
                "gross_brl": gross_brl,
                "calibration_factor": factor,
                "quality": quality,
                "calibration": calibration,
                "source_document_id": action["source_document_id"],
            }
        )
    return result


async def _receivable_for_day(
    repository,
    current_iso: str,
    actions: list[dict[str, Any]],
) -> tuple[Decimal, str, list[dict[str, Any]]] | None:
    active = [item for item in actions if item["ex_date"] <= current_iso < item["payment_date"]]
    if not active:
        return Decimal("0"), "NONE", []
    brl_fx = await _nearest_fx(repository, "BRL", current_iso)
    if brl_fx is None:
        return None
    rate = Decimal(str(brl_fx["rate"]))
    total = Decimal("0")
    components: list[dict[str, Any]] = []
    qualities: set[str] = set()
    for action in active:
        amount_nok = action["gross_brl"] * rate * action["calibration_factor"]
        total += amount_nok
        qualities.add(action["quality"])
        components.append(
            {
                "corporate_action_id": action["id"],
                "action_type": action["action_type"],
                "ex_date": action["ex_date"],
                "payment_date": action["payment_date"],
                "component_group": action["component_group"],
                "holding_id": action["holding_id"],
                "holding_shares": action["holding_shares"],
                "gross_brl": decimal_text(action["gross_brl"]),
                "brl_nok": decimal_text(rate),
                "brl_nok_date": brl_fx["rate_date"],
                "calibration_factor": decimal_text(action["calibration_factor"]),
                "quality": action["quality"],
                "calibration": action["calibration"],
                "amount_nok": decimal_text(amount_nok),
            }
        )
    quality = "ESTIMATED_GROSS" if "ESTIMATED_GROSS" in qualities else "REPORTED_CALIBRATED"
    return total, quality, components


async def refresh_other_net_assets_if_dirty(repository, as_of_date: str) -> dict[str, Any]:
    anchors = await _reported_ona_anchors(repository)
    current = date.fromisoformat(as_of_date)
    eligible = [item for item in anchors if date.fromisoformat(str(item["as_of_date"])) <= current]
    if not eligible:
        return {"status": "not_ready", "date": as_of_date, "reason": "missing_ona_anchor"}
    start_anchor = eligible[-1]
    start_index = anchors.index(start_anchor)
    start_day = date.fromisoformat(str(start_anchor["as_of_date"]))
    if current == start_day:
        end_anchor = start_anchor
        base_usd = _anchor_base_ex_option(start_anchor)
        quality = "REPORTED_ANCHOR"
    elif start_index + 1 < len(anchors):
        end_anchor = anchors[start_index + 1]
        end_day = date.fromisoformat(str(end_anchor["as_of_date"]))
        base_usd = _interpolated_base_ex_option(start_anchor, end_anchor, start_day, end_day, current)
        quality = "INTERPOLATED"
    else:
        end_anchor = None
        base_usd = _anchor_base_ex_option(start_anchor)
        quality = "FORECAST_PARTIAL"

    usd_fx = await _nearest_fx(repository, "USD", as_of_date)
    if usd_fx is None:
        return {"status": "not_ready", "date": as_of_date, "reason": "missing_usd_nok"}
    usd_nok = Decimal(str(usd_fx["rate"]))
    base_nok = base_usd * usd_nok
    receivable_actions = await _receivable_actions(repository)
    receivable_result = await _receivable_for_day(repository, as_of_date, receivable_actions)
    if receivable_result is None:
        return {"status": "not_ready", "date": as_of_date, "reason": "missing_brl_nok_for_receivable"}
    receivable_nok, receivable_quality, receivable_components = receivable_result
    option = await option_liability_for_day(repository, as_of_date)
    if option is None:
        return {"status": "not_ready", "date": as_of_date, "reason": "missing_option_inputs"}

    option_liability_nok = Decimal(option["liability_nok"])
    option_liability_usd = Decimal(option["liability_usd"])
    amount_nok = base_nok + receivable_nok - option_liability_nok
    amount_usd_equivalent = amount_nok / usd_nok if usd_nok != 0 else base_usd

    if current == start_day:
        tolerance = Decimal("0.01")
        reported_total_usd = Decimal(str(start_anchor["other_net_assets_reported"]))
        reported_receivable_usd = Decimal(str(start_anchor["associated_receivable_reported"]))
        reported_option_usd = Decimal(str(start_anchor.get("option_liability_reported") or "0"))
        if abs(amount_usd_equivalent - reported_total_usd) > tolerance:
            raise ValueError(
                f"Option-aware ONA does not reconcile at {as_of_date}: modeled USD "
                f"{amount_usd_equivalent} vs reported USD {reported_total_usd}"
            )
        if reported_receivable_usd == 0 and receivable_nok != 0:
            raise ValueError(f"Unexpected active receivable at zero-receivable report anchor {as_of_date}")
        if abs(option_liability_usd - reported_option_usd) > tolerance:
            raise ValueError(
                f"Option liability does not reconcile at {as_of_date}: modeled USD "
                f"{option_liability_usd} vs reported USD {reported_option_usd}"
            )

    payload = {
        "date": as_of_date,
        "base_ex_option_usd": decimal_text(base_usd),
        "base_ex_option_nok": decimal_text(base_nok),
        "usd_nok": decimal_text(usd_nok),
        "usd_fx_rate_id": usd_fx["id"],
        "associated_receivable_nok": decimal_text(receivable_nok),
        "receivable_quality": receivable_quality,
        "receivable_components": receivable_components,
        "option_liability_nok": decimal_text(option_liability_nok),
        "option_liability_usd": decimal_text(option_liability_usd),
        "option_quality": option["quality"],
        "option_inputs": option["inputs"],
        "start_anchor_id": start_anchor["id"],
        "end_anchor_id": end_anchor["id"] if end_anchor is not None else None,
        "quality": quality,
    }
    inputs_hash = _hash(payload)
    existing = await repository.first(
        "SELECT inputs_hash FROM other_net_assets_daily_estimates WHERE estimate_date=?",
        (as_of_date,),
    )
    if existing is not None and str(existing.get("inputs_hash")) == inputs_hash:
        return {
            "status": "ok",
            "date": as_of_date,
            "dirty": False,
            "skipped": True,
            "reason": "ona_inputs_unchanged",
            "inputs_hash": inputs_hash,
            "option_quality": option["quality"],
        }

    if quality == "REPORTED_ANCHOR":
        notes = "Reported ONA anchor; Bemobi receivable and cash-settled option obligation are decomposed explicitly."
    elif quality == "INTERPOLATED":
        notes = "Base ONA is reconstructed in USD without changing the pre-grant path; from the 15 Sep 2025 grant the cash-settled option obligation is separated and marked to market."
    else:
        notes = "Latest base ONA excluding the option obligation is carried forward in USD; Bemobi receivables remain event-driven and the cash-settled option obligation is marked to market using the latest reported valuation assumptions."

    await repository.run(
        """
        INSERT INTO other_net_assets_daily_estimates(
            estimate_date, amount_usd, usd_nok_rate, amount_nok, quality,
            start_anchor_id, end_anchor_id, inputs_hash, notes,
            base_amount_usd, base_amount_nok, associated_receivable_nok,
            receivable_quality, receivable_components_json,
            option_liability_nok, option_liability_usd,
            option_fair_value_per_option_nok, option_recognition_fraction,
            option_spot_nok, option_strike_nok, option_quality, option_inputs_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(estimate_date) DO UPDATE SET
            amount_usd=excluded.amount_usd,
            usd_nok_rate=excluded.usd_nok_rate,
            amount_nok=excluded.amount_nok,
            quality=excluded.quality,
            start_anchor_id=excluded.start_anchor_id,
            end_anchor_id=excluded.end_anchor_id,
            inputs_hash=excluded.inputs_hash,
            notes=excluded.notes,
            base_amount_usd=excluded.base_amount_usd,
            base_amount_nok=excluded.base_amount_nok,
            associated_receivable_nok=excluded.associated_receivable_nok,
            receivable_quality=excluded.receivable_quality,
            receivable_components_json=excluded.receivable_components_json,
            option_liability_nok=excluded.option_liability_nok,
            option_liability_usd=excluded.option_liability_usd,
            option_fair_value_per_option_nok=excluded.option_fair_value_per_option_nok,
            option_recognition_fraction=excluded.option_recognition_fraction,
            option_spot_nok=excluded.option_spot_nok,
            option_strike_nok=excluded.option_strike_nok,
            option_quality=excluded.option_quality,
            option_inputs_json=excluded.option_inputs_json,
            updated_at=strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        """,
        (
            as_of_date,
            decimal_text(amount_usd_equivalent),
            decimal_text(usd_nok),
            decimal_text(amount_nok),
            quality,
            start_anchor["id"],
            end_anchor["id"] if end_anchor is not None else None,
            inputs_hash,
            notes,
            decimal_text(base_usd),
            decimal_text(base_nok),
            decimal_text(receivable_nok),
            receivable_quality,
            json.dumps(receivable_components, sort_keys=True, ensure_ascii=False),
            decimal_text(option_liability_nok),
            decimal_text(option_liability_usd),
            decimal_text(option["fair_value_per_option_nok"]) if option["fair_value_per_option_nok"] is not None else None,
            decimal_text(option["recognition_fraction"]),
            decimal_text(option["spot_nok"]) if option["spot_nok"] is not None else None,
            decimal_text(option["strike_nok"]),
            option["quality"],
            json.dumps(option["inputs"], sort_keys=True, ensure_ascii=False),
        ),
    )
    return {
        "status": "ok",
        "date": as_of_date,
        "dirty": True,
        "skipped": False,
        "inputs_hash": inputs_hash,
        "amount_nok": decimal_text(amount_nok),
        "option_liability_nok": decimal_text(option_liability_nok),
        "option_quality": option["quality"],
        "receivable_quality": receivable_quality,
    }


async def refresh_full_nav_if_dirty(repository, as_of_date: str) -> dict[str, Any]:
    as_of_at = f"{as_of_date}T23:59:59Z"
    row = await repository.first(
        """
        SELECT n.id AS core_snapshot_id, n.as_of_at, n.nav_total_nok,
               n.nav_per_share_nok, n.otec_price_nok, n.bemobi_value_nok,
               n.cash_estimate_nok, n.shares_outstanding, n.status AS core_status,
               n.inputs_hash AS core_inputs_hash,
               o.rowid AS ona_daily_id, o.amount_usd, o.usd_nok_rate,
               o.amount_nok AS ona_nok, o.quality AS ona_quality,
               o.base_amount_usd, o.base_amount_nok,
               o.associated_receivable_nok, o.receivable_quality,
               o.receivable_components_json, o.inputs_hash AS ona_inputs_hash,
               o.option_liability_nok, o.option_liability_usd,
               o.option_fair_value_per_option_nok, o.option_recognition_fraction,
               o.option_spot_nok, o.option_strike_nok,
               o.option_quality, o.option_inputs_json
        FROM nav_snapshots n
        JOIN other_net_assets_daily_estimates o
          ON o.estimate_date=substr(n.as_of_at,1,10)
        WHERE n.as_of_at=? AND n.calculation_version=? AND n.nav_scope='CORE'
        LIMIT 1
        """,
        (as_of_at, CORE_CALCULATION_VERSION),
    )
    if row is None:
        return {"status": "not_ready", "date": as_of_date, "reason": "missing_core_or_ona"}

    core_total = Decimal(str(row["nav_total_nok"]))
    ona_nok = Decimal(str(row["ona_nok"]))
    shares = int(row["shares_outstanding"])
    full_total = core_total + ona_nok
    full_per_share = full_total / Decimal(shares)
    otec_price = Decimal(str(row["otec_price_nok"])) if row.get("otec_price_nok") is not None else None
    discount = (
        (Decimal("1") - otec_price / full_per_share) * Decimal("100")
        if otec_price is not None and full_per_share != 0 else None
    )
    degraded = (
        row["core_status"] == "DEGRADED"
        or row["ona_quality"] == "FORECAST_PARTIAL"
        or row["receivable_quality"] == "ESTIMATED_GROSS"
    )
    estimated = (
        row["core_status"] == "ESTIMATED"
        or row["ona_quality"] == "INTERPOLATED"
        or row["receivable_quality"] not in {"NONE", "REPORTED_CALIBRATED"}
        or row["option_quality"] in {"INTERPOLATED_TO_REPORTED", "FORECAST_MARK_TO_MARKET"}
    )
    status = "DEGRADED" if degraded else ("ESTIMATED" if estimated else "BACKFILLED")
    try:
        receivable_components = json.loads(row.get("receivable_components_json") or "[]")
    except (TypeError, json.JSONDecodeError):
        receivable_components = []
    try:
        option_inputs = json.loads(row.get("option_inputs_json") or "{}")
    except (TypeError, json.JSONDecodeError):
        option_inputs = {}
    components = {
        "scope": "FULL",
        "core_snapshot_id": row["core_snapshot_id"],
        "core_calculation_version": CORE_CALCULATION_VERSION,
        "core_inputs_hash": row["core_inputs_hash"],
        "full_nav_methodology": "option-liability-v1",
        "other_net_assets": {
            "daily_estimate_id": row["ona_daily_id"],
            "amount_usd_equivalent": row["amount_usd"],
            "usd_nok": row["usd_nok_rate"],
            "amount_nok": row["ona_nok"],
            "base_ex_option_amount_usd": row["base_amount_usd"],
            "base_ex_option_amount_nok": row["base_amount_nok"],
            "associated_receivable_nok": row["associated_receivable_nok"],
            "receivable_quality": row["receivable_quality"],
            "receivable_components": receivable_components,
            "option_liability": {
                "amount_nok": row["option_liability_nok"],
                "amount_usd": row["option_liability_usd"],
                "fair_value_per_option_nok": row["option_fair_value_per_option_nok"],
                "recognition_fraction": row["option_recognition_fraction"],
                "spot_nok": row["option_spot_nok"],
                "strike_nok": row["option_strike_nok"],
                "quality": row["option_quality"],
                "inputs": option_inputs,
            },
            "quality": row["ona_quality"],
            "inputs_hash": row["ona_inputs_hash"],
        },
    }
    inputs_hash = _hash(components)
    existing = await repository.first(
        "SELECT id, inputs_hash FROM nav_snapshots WHERE as_of_at=? AND calculation_version=? LIMIT 1",
        (as_of_at, FULL_CALCULATION_VERSION),
    )
    if existing is not None and str(existing.get("inputs_hash")) == inputs_hash:
        return {
            "status": "ok",
            "date": as_of_date,
            "dirty": False,
            "skipped": True,
            "reason": "full_inputs_unchanged",
            "snapshot_id": int(existing["id"]),
            "inputs_hash": inputs_hash,
        }

    quality_notes = (
        "FULL NAV = stored CORE NAV + option-aware other net assets/liabilities. "
        "Base ONA excludes both Bemobi distribution receivables and the cash-settled Otello option obligation. "
        "Bemobi receivables are valued separately from entitlement/ex-date until payment. "
        "From 15 Sep 2025 the option obligation is marked to market from OTEC using the reported Black-Scholes framework and is calibrated to the audited USD 314k liability at 31 Dec 2025."
    )
    if row["ona_quality"] == "FORECAST_PARTIAL":
        quality_notes += " Base ONA excluding the option obligation is carried forward after the latest report and is therefore partial forecast data."
    elif row["ona_quality"] == "INTERPOLATED":
        quality_notes += " Base ONA excluding the option obligation is interpolated between reported anchors and is therefore estimated for this date."
    if row["receivable_quality"] == "ESTIMATED_GROSS":
        quality_notes += " At least one active Bemobi receivable is gross-estimated because no report-date receivable anchor exists inside its lifecycle."
    if row["option_quality"] == "FORECAST_MARK_TO_MARKET":
        quality_notes += " The option liability uses the latest reported risk-free-rate/volatility assumptions until a new Otello report supplies updated valuation inputs."

    await repository.run(
        """
        INSERT INTO nav_snapshots(
            as_of_at, nav_total_nok, nav_per_share_nok, otec_price_nok,
            discount_pct, bemobi_value_nok, cash_estimate_nok,
            other_net_assets_nok, shares_outstanding, calculation_version,
            inputs_hash, status, nav_scope, components_json, quality_notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'FULL', ?, ?)
        ON CONFLICT(as_of_at, calculation_version) DO UPDATE SET
            nav_total_nok=excluded.nav_total_nok,
            nav_per_share_nok=excluded.nav_per_share_nok,
            otec_price_nok=excluded.otec_price_nok,
            discount_pct=excluded.discount_pct,
            bemobi_value_nok=excluded.bemobi_value_nok,
            cash_estimate_nok=excluded.cash_estimate_nok,
            other_net_assets_nok=excluded.other_net_assets_nok,
            shares_outstanding=excluded.shares_outstanding,
            inputs_hash=excluded.inputs_hash,
            status=excluded.status,
            nav_scope=excluded.nav_scope,
            components_json=excluded.components_json,
            quality_notes=excluded.quality_notes
        """,
        (
            as_of_at,
            decimal_text(full_total),
            decimal_text(full_per_share),
            decimal_text(otec_price) if otec_price is not None else None,
            decimal_text(discount) if discount is not None else None,
            row["bemobi_value_nok"],
            row["cash_estimate_nok"],
            decimal_text(ona_nok),
            shares,
            FULL_CALCULATION_VERSION,
            inputs_hash,
            status,
            json.dumps(components, sort_keys=True, ensure_ascii=False),
            quality_notes,
        ),
    )
    latest = await repository.first(
        "SELECT id FROM nav_snapshots WHERE as_of_at=? AND calculation_version=? LIMIT 1",
        (as_of_at, FULL_CALCULATION_VERSION),
    )
    return {
        "status": "ok",
        "date": as_of_date,
        "dirty": True,
        "skipped": False,
        "snapshot_id": int(latest["id"]) if latest else None,
        "inputs_hash": inputs_hash,
        "nav_per_share_nok": decimal_text(full_per_share),
        "option_quality": row["option_quality"],
    }


async def refresh_dirty_nav_layers(repository, *, target_date: str) -> dict[str, Any]:
    """Recompute only the current model date whose deterministic inputs are dirty."""
    nav_date, live_calendar_snapshot = await _latest_nav_date(repository, target_date)
    if nav_date is None:
        return {
            "status": "not_ready",
            "target_date": target_date,
            "nav_date": None,
            "reason": "no_otec_market_date",
        }

    steps: dict[str, Any] = {}
    steps["daily_cash"] = await refresh_daily_cash_if_dirty(repository, nav_date)
    steps["daily_other_net_assets"] = await refresh_other_net_assets_if_dirty(repository, nav_date)
    steps["daily_core_nav"] = await refresh_core_nav_if_dirty(repository, nav_date)
    steps["daily_full_nav"] = await refresh_full_nav_if_dirty(repository, nav_date)

    not_ready = [name for name, result in steps.items() if result.get("status") != "ok"]
    dirty = [name for name, result in steps.items() if result.get("dirty") is True]
    return {
        "status": "ok" if not not_ready else "partial",
        "target_date": target_date,
        "nav_date": nav_date,
        "live_calendar_snapshot": live_calendar_snapshot,
        "dirty_layers": dirty,
        "not_ready_layers": not_ready,
        "steps": steps,
    }

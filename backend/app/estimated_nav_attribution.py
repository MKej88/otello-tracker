from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from decimal import Decimal
from typing import Any


MAX_MARKET_LOOKBACK_DAYS = 7
ATTRIBUTION_TOLERANCE_NOK = Decimal("1000")


def symmetric_two_factor_attribution(
    *,
    shares: int,
    start_price: Decimal,
    current_price: Decimal,
    start_fx: Decimal,
    current_fx: Decimal,
) -> dict[str, Decimal]:
    """Fordel verdiendringen symmetrisk mellom aksjekurs og valutakurs."""
    quantity = Decimal(shares)
    total = quantity * (current_price * current_fx - start_price * start_fx)
    price_effect = (
        quantity
        * (current_price - start_price)
        * (start_fx + current_fx)
        / Decimal("2")
    )
    return {
        "total_change_nok": total,
        "price_effect_nok": price_effect,
        "fx_effect_nok": total - price_effect,
    }


def _preferred_price(
    connection: sqlite3.Connection,
    symbol: str,
    as_of_date: str,
) -> sqlite3.Row | None:
    floor_date = (
        date.fromisoformat(as_of_date) - timedelta(days=MAX_MARKET_LOOKBACK_DAYS)
    ).isoformat()
    return connection.execute(
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
    ).fetchone()


def _preferred_fx(
    connection: sqlite3.Connection,
    base: str,
    day: str,
) -> sqlite3.Row | None:
    floor_date = (
        date.fromisoformat(day) - timedelta(days=MAX_MARKET_LOOKBACK_DAYS)
    ).isoformat()
    return connection.execute(
        """
        SELECT fr.id, substr(fr.observed_at,1,10) AS rate_date, fr.rate
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
        (base, day, floor_date),
    ).fetchone()


def _holding(
    connection: sqlite3.Connection,
    as_of_date: str,
) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT id, shares, ownership_pct, effective_from, effective_to
        FROM bemobi_holdings
        WHERE effective_from <= ? AND (effective_to IS NULL OR effective_to >= ?)
        ORDER BY effective_from DESC, id DESC LIMIT 1
        """,
        (as_of_date, as_of_date),
    ).fetchone()


def bemobi_market_attribution(
    connection: sqlite3.Connection,
    *,
    start_date: str,
    current_date: str,
    expected_change_nok: Decimal,
) -> dict[str, Any]:
    start_price = _preferred_price(connection, "BMOB3", start_date)
    current_price = _preferred_price(connection, "BMOB3", current_date)
    start_fx = _preferred_fx(connection, "BRL", start_date)
    current_fx = _preferred_fx(connection, "BRL", current_date)
    start_holding = _holding(connection, start_date)
    current_holding = _holding(connection, current_date)
    inputs = (
        start_price,
        current_price,
        start_fx,
        current_fx,
        start_holding,
        current_holding,
    )
    if any(value is None for value in inputs):
        return {"ready": False, "reason": "missing_bemobi_attribution_inputs"}

    # Sjekken over gjør alle verdiene trygge å bruke. De eksplisitte kontrollene
    # hjelper samtidig Mypy med å forstå dette uten komplisert typekode.
    assert start_price is not None
    assert current_price is not None
    assert start_fx is not None
    assert current_fx is not None
    assert start_holding is not None
    assert current_holding is not None

    start_holding_shares = int(start_holding["shares"])
    current_holding_shares = int(current_holding["shares"])
    if start_holding_shares != current_holding_shares:
        return {
            "ready": False,
            "reason": "bemobi_holding_changed",
            "start_holding_shares": start_holding_shares,
            "current_holding_shares": current_holding_shares,
        }

    attribution = symmetric_two_factor_attribution(
        shares=start_holding_shares,
        start_price=Decimal(str(start_price["price"])),
        current_price=Decimal(str(current_price["price"])),
        start_fx=Decimal(str(start_fx["rate"])),
        current_fx=Decimal(str(current_fx["rate"])),
    )
    if (
        abs(attribution["total_change_nok"] - expected_change_nok)
        > ATTRIBUTION_TOLERANCE_NOK
    ):
        return {
            "ready": False,
            "reason": "bemobi_attribution_does_not_reconcile",
            "expected_change_nok": expected_change_nok,
            **attribution,
        }

    return {
        "ready": True,
        "method": "SYMMETRIC_TWO_FACTOR_SHAPLEY",
        "holding_shares": start_holding_shares,
        "start_price_brl": Decimal(str(start_price["price"])),
        "current_price_brl": Decimal(str(current_price["price"])),
        "start_price_date": str(start_price["trading_date"]),
        "current_price_date": str(current_price["trading_date"]),
        "start_brl_nok": Decimal(str(start_fx["rate"])),
        "current_brl_nok": Decimal(str(current_fx["rate"])),
        "start_fx_date": str(start_fx["rate_date"]),
        "current_fx_date": str(current_fx["rate_date"]),
        **attribution,
    }

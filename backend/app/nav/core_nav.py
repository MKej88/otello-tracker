from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from app.db.connection import get_connection
from app.db.repository import decimal_text

CALCULATION_VERSION = "core-market-nav-v1"
MAX_LOOKBACK_DAYS = 7


def _nearest_price(connection, symbol: str, as_of_date: str):
    floor_date = (date.fromisoformat(as_of_date) - timedelta(days=MAX_LOOKBACK_DAYS)).isoformat()
    return connection.execute(
        """
        SELECT mp.id, mp.trading_date, mp.price, mp.source_document_id
        FROM market_prices mp
        JOIN instruments i ON i.id = mp.instrument_id
        WHERE i.symbol = ? AND mp.price_type = 'CLOSE'
          AND mp.trading_date <= ? AND mp.trading_date >= ?
        ORDER BY mp.trading_date DESC, mp.id DESC
        LIMIT 1
        """,
        (symbol, as_of_date, floor_date),
    ).fetchone()


def _nearest_fx(connection, base: str, as_of_date: str):
    floor_date = (date.fromisoformat(as_of_date) - timedelta(days=MAX_LOOKBACK_DAYS)).isoformat()
    return connection.execute(
        """
        SELECT id, substr(observed_at, 1, 10) AS rate_date, rate, source_document_id
        FROM fx_rates
        WHERE base_currency = ? AND quote_currency = 'NOK'
          AND substr(observed_at, 1, 10) <= ?
          AND substr(observed_at, 1, 10) >= ?
        ORDER BY observed_at DESC, id DESC
        LIMIT 1
        """,
        (base, as_of_date, floor_date),
    ).fetchone()


def _holding(connection, as_of_date: str):
    return connection.execute(
        """
        SELECT id, shares, ownership_pct, effective_from, effective_to
        FROM bemobi_holdings
        WHERE effective_from <= ? AND (effective_to IS NULL OR effective_to >= ?)
        ORDER BY effective_from DESC, id DESC LIMIT 1
        """,
        (as_of_date, as_of_date),
    ).fetchone()


def _share_count(connection, as_of_date: str):
    return connection.execute(
        """
        SELECT id, effective_from, total_shares, treasury_shares, outstanding_shares
        FROM otello_share_counts
        WHERE effective_from <= ?
        ORDER BY effective_from DESC, id DESC LIMIT 1
        """,
        (as_of_date,),
    ).fetchone()


def _cash_anchor(connection, as_of_date: str):
    return connection.execute(
        """
        SELECT id, as_of_date, amount_nok, reported_amount, reported_currency,
               fx_rate_to_nok, source_document_id
        FROM cash_anchors
        WHERE as_of_date = ? AND anchor_type = 'REPORTED'
        ORDER BY id DESC LIMIT 1
        """,
        (as_of_date,),
    ).fetchone()


def _canonical_hash(components: dict[str, Any]) -> str:
    payload = json.dumps(components, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def calculate_core_nav_anchor(connection, as_of_date: str) -> dict[str, Any]:
    bm_price = _nearest_price(connection, "BMOB3", as_of_date)
    otec_price = _nearest_price(connection, "OTEC", as_of_date)
    brl_nok = _nearest_fx(connection, "BRL", as_of_date)
    usd_nok = _nearest_fx(connection, "USD", as_of_date)
    holding = _holding(connection, as_of_date)
    shares = _share_count(connection, as_of_date)
    cash = _cash_anchor(connection, as_of_date)

    required = {
        "BMOB3 close": bm_price,
        "BRL/NOK": brl_nok,
        "USD/NOK": usd_nok,
        "Bemobi holding": holding,
        "OTEC share count": shares,
        "cash anchor": cash,
    }
    missing = [name for name, value in required.items() if value is None]
    if missing:
        return {"as_of_date": as_of_date, "ready": False, "missing": missing}

    if cash["reported_currency"] != "USD":
        raise ValueError(
            f"Core NAV v1 forventer USD cash-anchor, fikk {cash['reported_currency']} {as_of_date}"
        )

    bmob3_price_brl = Decimal(bm_price["price"])
    brl_nok_rate = Decimal(brl_nok["rate"])
    usd_nok_rate = Decimal(usd_nok["rate"])
    holding_shares = int(holding["shares"])
    outstanding = int(shares["outstanding_shares"])
    cash_usd = Decimal(cash["reported_amount"])

    bemobi_value_nok = bmob3_price_brl * Decimal(holding_shares) * brl_nok_rate
    cash_nok = cash_usd * usd_nok_rate
    core_nav_total = bemobi_value_nok + cash_nok
    nav_per_share = core_nav_total / Decimal(outstanding)

    otec_price_nok = Decimal(otec_price["price"]) if otec_price is not None else None
    discount_pct = (
        (Decimal("1") - otec_price_nok / nav_per_share) * Decimal("100")
        if otec_price_nok is not None
        else None
    )

    components = {
        "scope": "CORE",
        "as_of_date": as_of_date,
        "bmob3": {
            "price_id": bm_price["id"],
            "trading_date": bm_price["trading_date"],
            "close_brl": bm_price["price"],
            "holding_id": holding["id"],
            "shares": holding_shares,
            "brl_nok_id": brl_nok["id"],
            "brl_nok_date": brl_nok["rate_date"],
            "brl_nok": brl_nok["rate"],
        },
        "cash": {
            "anchor_id": cash["id"],
            "cash_usd": cash["reported_amount"],
            "usd_nok_id": usd_nok["id"],
            "usd_nok_date": usd_nok["rate_date"],
            "usd_nok": usd_nok["rate"],
        },
        "otec": {
            "share_count_id": shares["id"],
            "outstanding_shares": outstanding,
            "price_id": otec_price["id"] if otec_price is not None else None,
            "price_date": otec_price["trading_date"] if otec_price is not None else None,
            "price_nok": otec_price["price"] if otec_price is not None else None,
        },
    }

    return {
        "as_of_date": as_of_date,
        "ready": True,
        "nav_total_nok": core_nav_total,
        "nav_per_share_nok": nav_per_share,
        "otec_price_nok": otec_price_nok,
        "discount_pct": discount_pct,
        "bemobi_value_nok": bemobi_value_nok,
        "cash_nok": cash_nok,
        "other_net_assets_nok": Decimal("0"),
        "shares_outstanding": outstanding,
        "components": components,
        "inputs_hash": _canonical_hash(components),
    }


def rebuild_core_nav_anchors(database_path: str | None = None) -> dict[str, Any]:
    """Calculate conservative report-date CORE NAV snapshots.

    CORE deliberately means Bemobi market value + reported cash only. It is not labelled
    FULL NAV until other net assets/liabilities have been reconstructed. This prevents
    the dashboard from overstating historical model completeness.
    """
    written = 0
    skipped: list[dict[str, Any]] = []
    with get_connection(database_path) as connection:
        dates = [
            row["as_of_date"]
            for row in connection.execute(
                "SELECT DISTINCT as_of_date FROM cash_anchors WHERE anchor_type = 'REPORTED' ORDER BY as_of_date"
            )
        ]
        for as_of_date in dates:
            result = calculate_core_nav_anchor(connection, as_of_date)
            if not result["ready"]:
                skipped.append(result)
                continue

            connection.execute(
                """
                INSERT INTO nav_snapshots(
                    as_of_at, nav_total_nok, nav_per_share_nok, otec_price_nok,
                    discount_pct, bemobi_value_nok, cash_estimate_nok,
                    other_net_assets_nok, shares_outstanding, calculation_version,
                    inputs_hash, status, nav_scope, components_json, quality_notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'BACKFILLED', 'CORE', ?, ?)
                ON CONFLICT(as_of_at, calculation_version)
                DO UPDATE SET
                    nav_total_nok = excluded.nav_total_nok,
                    nav_per_share_nok = excluded.nav_per_share_nok,
                    otec_price_nok = excluded.otec_price_nok,
                    discount_pct = excluded.discount_pct,
                    bemobi_value_nok = excluded.bemobi_value_nok,
                    cash_estimate_nok = excluded.cash_estimate_nok,
                    other_net_assets_nok = excluded.other_net_assets_nok,
                    shares_outstanding = excluded.shares_outstanding,
                    inputs_hash = excluded.inputs_hash,
                    status = excluded.status,
                    nav_scope = excluded.nav_scope,
                    components_json = excluded.components_json,
                    quality_notes = excluded.quality_notes
                """,
                (
                    f"{as_of_date}T23:59:59Z",
                    decimal_text(result["nav_total_nok"]),
                    decimal_text(result["nav_per_share_nok"]),
                    decimal_text(result["otec_price_nok"]) if result["otec_price_nok"] is not None else None,
                    decimal_text(result["discount_pct"]) if result["discount_pct"] is not None else None,
                    decimal_text(result["bemobi_value_nok"]),
                    decimal_text(result["cash_nok"]),
                    decimal_text(result["other_net_assets_nok"]),
                    result["shares_outstanding"],
                    CALCULATION_VERSION,
                    result["inputs_hash"],
                    json.dumps(result["components"], sort_keys=True, ensure_ascii=False),
                    "CORE NAV: Bemobi market value + reported cash only; other net assets/liabilities are not yet reconstructed.",
                ),
            )
            written += 1
        connection.commit()

    return {
        "calculation_version": CALCULATION_VERSION,
        "written": written,
        "skipped": skipped,
    }

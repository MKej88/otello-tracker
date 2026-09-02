from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from app.db.connection import get_connection
from app.db.repository import decimal_text

CALCULATION_VERSION = "core-market-nav-daily-v1"
MAX_LOOKBACK_DAYS = 7


def _canonical_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _preferred_price(connection, symbol: str, as_of_date: str):
    """Prefer the freshest authoritative price while keeping CLOSE stronger than LAST.

    Historical imports remain CLOSE. Euronext's public delayed trade file is intraday and
    therefore stored as LAST, never mislabeled as an official close. A newer Euronext
    LAST can still beat an older trading date, and official Euronext data beats a same-day
    third-party fallback. If both Euronext CLOSE and LAST exist on the same date, CLOSE
    wins because it has the stronger price semantic.
    """
    floor_date = (
        date.fromisoformat(as_of_date) - timedelta(days=MAX_LOOKBACK_DAYS)
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


def _nearest_fx(connection, base: str, as_of_date: str):
    floor_date = (
        date.fromisoformat(as_of_date) - timedelta(days=MAX_LOOKBACK_DAYS)
    ).isoformat()
    return connection.execute(
        """
        SELECT fr.id, fr.observed_at,
               substr(fr.observed_at,1,10) AS rate_date, fr.rate,
               fr.source_document_id, s.code AS source_code
        FROM fx_rates fr
        JOIN sources s ON s.id = fr.source_id
        WHERE fr.base_currency = ? AND fr.quote_currency = 'NOK'
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


def _cash(connection, as_of_date: str):
    return connection.execute(
        """
        SELECT c.id, c.estimate_date, c.cash_nok, c.quality, c.inputs_hash,
               c.period_start_date, c.period_end_date,
               p.quality AS calibration_quality
        FROM cash_daily_estimates c
        LEFT JOIN cash_period_calibrations p
          ON p.start_anchor_date = c.period_start_date
         AND p.end_anchor_date = c.period_end_date
        WHERE c.estimate_date = ?
        """,
        (as_of_date,),
    ).fetchone()


def _share_count_may_be_stale(
    connection, as_of_date: str, share_count_date: str
) -> bool:
    """Flag known/potential buyback lag independently of cash quality."""
    latest = connection.execute(
        """
        SELECT b.trade_date, b.cumulative_program_shares, p.max_shares
        FROM buybacks b
        LEFT JOIN buyback_programs p ON p.id = b.program_id
        WHERE b.trade_date <= ?
        ORDER BY b.trade_date DESC, b.id DESC
        LIMIT 1
        """,
        (as_of_date,),
    ).fetchone()
    return _share_count_is_stale(as_of_date, share_count_date, latest)


def _share_count_is_stale(as_of_date: str, share_count_date: str, latest: Any) -> bool:
    if latest is None:
        return False

    if share_count_date < latest["trade_date"]:
        return True
    if share_count_date > latest["trade_date"] or as_of_date == share_count_date:
        return False

    max_shares = latest["max_shares"]
    cumulative = latest["cumulative_program_shares"]
    if max_shares is None or cumulative is None or int(cumulative) >= int(max_shares):
        return False

    age = (
        date.fromisoformat(as_of_date) - date.fromisoformat(latest["trade_date"])
    ).days
    return 0 < age <= 14


def _load_daily_reference_data(
    connection, dates: list[str]
) -> dict[str, dict[str, Any]]:
    """Load slowly changing NAV inputs once instead of querying for every day."""
    if not dates:
        return {}

    end_date = dates[-1]
    holdings = connection.execute(
        """
        SELECT id, shares, ownership_pct, effective_from, effective_to
        FROM bemobi_holdings
        WHERE effective_from <= ?
        ORDER BY effective_from, id
        """,
        (end_date,),
    ).fetchall()
    share_counts = connection.execute(
        """
        SELECT id, effective_from, total_shares, treasury_shares, outstanding_shares
        FROM otello_share_counts
        WHERE effective_from <= ?
        ORDER BY effective_from, id
        """,
        (end_date,),
    ).fetchall()
    buybacks = connection.execute(
        """
        SELECT b.id, b.trade_date, b.cumulative_program_shares, p.max_shares
        FROM buybacks b
        LEFT JOIN buyback_programs p ON p.id = b.program_id
        WHERE b.trade_date <= ?
        ORDER BY b.trade_date, b.id
        """,
        (end_date,),
    ).fetchall()

    result: dict[str, dict[str, Any]] = {}
    for current in dates:
        holding = next(
            (
                row
                for row in reversed(holdings)
                if row["effective_from"] <= current
                and (row["effective_to"] is None or row["effective_to"] >= current)
            ),
            None,
        )
        share_count = next(
            (row for row in reversed(share_counts) if row["effective_from"] <= current),
            None,
        )
        latest_buyback = next(
            (row for row in reversed(buybacks) if row["trade_date"] <= current),
            None,
        )
        result[current] = {
            "holding": holding,
            "share_count": share_count,
            "latest_buyback": latest_buyback,
        }
    return result


def calculate_daily_core_nav(
    connection,
    as_of_date: str,
    *,
    reference_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    bmob3 = _preferred_price(connection, "BMOB3", as_of_date)
    otec = _preferred_price(connection, "OTEC", as_of_date)
    brl_nok = _nearest_fx(connection, "BRL", as_of_date)
    holding = (
        reference_data["holding"]
        if reference_data is not None
        else _holding(connection, as_of_date)
    )
    shares = (
        reference_data["share_count"]
        if reference_data is not None
        else _share_count(connection, as_of_date)
    )
    cash = _cash(connection, as_of_date)

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

    bmob3_price = Decimal(bmob3["price"])
    brl_nok_rate = Decimal(brl_nok["rate"])
    otec_price = Decimal(otec["price"])
    cash_nok = Decimal(cash["cash_nok"])
    holding_shares = int(holding["shares"])
    outstanding = int(shares["outstanding_shares"])

    bemobi_value = bmob3_price * Decimal(holding_shares) * brl_nok_rate
    nav_total = bemobi_value + cash_nok
    nav_per_share = nav_total / Decimal(outstanding)
    discount = (Decimal("1") - otec_price / nav_per_share) * Decimal("100")

    if reference_data is None:
        stale_share_count = _share_count_may_be_stale(
            connection, as_of_date, shares["effective_from"]
        )
    else:
        stale_share_count = _share_count_is_stale(
            as_of_date,
            shares["effective_from"],
            reference_data["latest_buyback"],
        )
    high_residual = cash["calibration_quality"] == "HIGH_RESIDUAL"
    forecast_partial = cash["quality"] == "FORECAST_PARTIAL"

    if forecast_partial or high_residual or stale_share_count:
        status = "DEGRADED"
    elif cash["quality"] == "ANCHORED_ESTIMATE":
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
            "brl_nok_observed_at": brl_nok["observed_at"],
            "brl_nok": brl_nok["rate"],
            "brl_nok_source": brl_nok["source_code"],
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
            "share_count_quality": (
                "POTENTIALLY_STALE" if stale_share_count else "CURRENT_KNOWN"
            ),
        },
        "cash": {
            "daily_cash_id": cash["id"],
            "cash_nok": cash["cash_nok"],
            "quality": cash["quality"],
            "calibration_quality": cash["calibration_quality"],
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
        "inputs_hash": _canonical_hash(components),
        "quality_notes": notes,
    }


def rebuild_daily_core_nav(
    database_path: str | None = None,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    written = 0
    skipped: list[dict[str, Any]] = []
    with get_connection(database_path) as connection:
        cash_range = connection.execute(
            "SELECT MIN(estimate_date) AS min_date, MAX(estimate_date) AS max_date FROM cash_daily_estimates"
        ).fetchone()
        if cash_range["min_date"] is None:
            return {"written": 0, "skipped": [], "error": "daily cash curve is empty"}
        start = start_date or cash_range["min_date"]
        end = end_date or cash_range["max_date"]

        dates = [
            row["trading_date"]
            for row in connection.execute(
                """
                SELECT DISTINCT mp.trading_date
                FROM market_prices mp
                JOIN instruments i ON i.id = mp.instrument_id
                WHERE i.symbol = 'OTEC' AND mp.trading_date >= ? AND mp.trading_date <= ?
                ORDER BY mp.trading_date
                """,
                (start, end),
            )
        ]
        reference_data = _load_daily_reference_data(connection, dates)
        for current in dates:
            result = calculate_daily_core_nav(
                connection, current, reference_data=reference_data[current]
            )
            if not result["ready"]:
                skipped.append(result)
                continue
            cursor = connection.execute(
                """
                INSERT INTO nav_snapshots(
                    as_of_at, nav_total_nok, nav_per_share_nok, otec_price_nok,
                    discount_pct, bemobi_value_nok, cash_estimate_nok,
                    other_net_assets_nok, shares_outstanding, calculation_version,
                    inputs_hash, status, nav_scope, components_json, quality_notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'CORE', ?, ?)
                ON CONFLICT(as_of_at, calculation_version) DO UPDATE SET
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
                WHERE nav_snapshots.inputs_hash <> excluded.inputs_hash
                   OR nav_snapshots.status <> excluded.status
                   OR nav_snapshots.nav_scope <> excluded.nav_scope
                   OR nav_snapshots.quality_notes <> excluded.quality_notes
                """,
                (
                    f"{current}T23:59:59Z",
                    decimal_text(result["nav_total_nok"]),
                    decimal_text(result["nav_per_share_nok"]),
                    decimal_text(result["otec_price_nok"]),
                    decimal_text(result["discount_pct"]),
                    decimal_text(result["bemobi_value_nok"]),
                    decimal_text(result["cash_nok"]),
                    decimal_text(result["other_net_assets_nok"]),
                    result["shares_outstanding"],
                    CALCULATION_VERSION,
                    result["inputs_hash"],
                    result["status"],
                    json.dumps(
                        result["components"], sort_keys=True, ensure_ascii=False
                    ),
                    result["quality_notes"],
                ),
            )
            written += cursor.rowcount
        connection.commit()
    return {
        "calculation_version": CALCULATION_VERSION,
        "written": written,
        "skipped": skipped,
        "from": start,
        "to": end,
    }


def daily_nav_status(database_path: str | None = None) -> dict[str, Any]:
    with get_connection(database_path) as connection:
        aggregate = connection.execute(
            """
            SELECT COUNT(*) AS n, MIN(substr(as_of_at,1,10)) AS min_date,
                   MAX(substr(as_of_at,1,10)) AS max_date,
                   SUM(CASE WHEN status = 'DEGRADED' THEN 1 ELSE 0 END) AS degraded,
                   SUM(CASE WHEN status = 'ESTIMATED' THEN 1 ELSE 0 END) AS estimated
            FROM nav_snapshots
            WHERE calculation_version = ?
            """,
            (CALCULATION_VERSION,),
        ).fetchone()
        latest = connection.execute(
            """
            SELECT as_of_at, nav_per_share_nok, otec_price_nok, discount_pct,
                   cash_estimate_nok, shares_outstanding, status, quality_notes
            FROM nav_snapshots WHERE calculation_version = ?
            ORDER BY as_of_at DESC LIMIT 1
            """,
            (CALCULATION_VERSION,),
        ).fetchone()
        return {
            "status": "ok" if aggregate["n"] else "empty",
            "calculation_version": CALCULATION_VERSION,
            "count": aggregate["n"],
            "from": aggregate["min_date"],
            "to": aggregate["max_date"],
            "degraded": aggregate["degraded"],
            "estimated": aggregate["estimated"],
            "latest": dict(latest) if latest is not None else None,
        }

from __future__ import annotations

import json
from typing import Any

from app.db.connection import get_connection
from app.db.repository import decimal_text
from app.nav.daily_nav import CALCULATION_VERSION, calculate_daily_core_nav


def rebuild_core_nav_for_date(
    database_path: str | None,
    *,
    as_of_date: str,
) -> dict[str, Any]:
    """Build one explicit calendar-date CORE snapshot using normal lookback rules.

    The regular historical rebuild intentionally iterates OTEC trading dates. Intraday,
    however, BMOB3 can move on a day before OTEC has traded. This helper creates an
    indicative snapshot for that calendar date while reusing the exact same NAV formula
    and the existing seven-day market/FX lookbacks. Timestamp enrichment then marks mixed
    component dates explicitly instead of silently leaving a fresh BMOB3 quote unused.
    """
    with get_connection(database_path) as connection:
        result = calculate_daily_core_nav(connection, as_of_date)
        if not result["ready"]:
            return {
                "calculation_version": CALCULATION_VERSION,
                "written": 0,
                "skipped": [result],
                "from": as_of_date,
                "to": as_of_date,
            }

        connection.execute(
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
            """,
            (
                f"{as_of_date}T23:59:59Z",
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
                json.dumps(result["components"], sort_keys=True, ensure_ascii=False),
                result["quality_notes"],
            ),
        )
        connection.commit()

    return {
        "calculation_version": CALCULATION_VERSION,
        "written": 1,
        "skipped": [],
        "from": as_of_date,
        "to": as_of_date,
        "indicative_calendar_date": True,
    }

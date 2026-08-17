from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any

from app.db.connection import get_connection
from app.db.repository import decimal_text
from app.nav.daily_nav import CALCULATION_VERSION as CORE_CALCULATION_VERSION

FULL_CALCULATION_VERSION = "full-market-nav-daily-v2"


def _hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def rebuild_daily_full_nav(
    database_path: str | None = None,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    written = 0
    with get_connection(database_path) as connection:
        clauses = ["n.calculation_version = ?", "n.nav_scope = 'CORE'"]
        params: list[Any] = [CORE_CALCULATION_VERSION]
        if start_date is not None:
            clauses.append("substr(n.as_of_at, 1, 10) >= ?")
            params.append(start_date)
        if end_date is not None:
            clauses.append("substr(n.as_of_at, 1, 10) <= ?")
            params.append(end_date)
        rows = connection.execute(
            f"""
            SELECT n.id AS core_snapshot_id, n.as_of_at, n.nav_total_nok,
                   n.nav_per_share_nok, n.otec_price_nok, n.bemobi_value_nok,
                   n.cash_estimate_nok, n.shares_outstanding, n.status AS core_status,
                   n.inputs_hash AS core_inputs_hash, n.components_json AS core_components_json,
                   o.rowid AS ona_daily_id, o.amount_usd, o.usd_nok_rate,
                   o.amount_nok AS ona_nok, o.quality AS ona_quality,
                   o.base_amount_usd, o.base_amount_nok,
                   o.associated_receivable_nok, o.receivable_quality,
                   o.receivable_components_json, o.inputs_hash AS ona_inputs_hash
            FROM nav_snapshots n
            JOIN other_net_assets_daily_estimates o
              ON o.estimate_date = substr(n.as_of_at, 1, 10)
            WHERE {' AND '.join(clauses)}
            ORDER BY n.as_of_at
            """,
            params,
        ).fetchall()

        for row in rows:
            core_total = Decimal(row["nav_total_nok"])
            ona_nok = Decimal(row["ona_nok"])
            shares = int(row["shares_outstanding"])
            full_total = core_total + ona_nok
            full_per_share = full_total / Decimal(shares)
            otec_price = Decimal(row["otec_price_nok"]) if row["otec_price_nok"] is not None else None
            discount = (
                (Decimal("1") - otec_price / full_per_share) * Decimal("100")
                if otec_price is not None and full_per_share != 0
                else None
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
            )
            if degraded:
                status = "DEGRADED"
            elif estimated:
                status = "ESTIMATED"
            else:
                status = "BACKFILLED"

            receivable_components = json.loads(row["receivable_components_json"] or "[]")
            components = {
                "scope": "FULL",
                "core_snapshot_id": row["core_snapshot_id"],
                "core_calculation_version": CORE_CALCULATION_VERSION,
                "core_inputs_hash": row["core_inputs_hash"],
                "other_net_assets": {
                    "daily_estimate_id": row["ona_daily_id"],
                    "amount_usd_equivalent": row["amount_usd"],
                    "usd_nok": row["usd_nok_rate"],
                    "amount_nok": row["ona_nok"],
                    "base_amount_usd": row["base_amount_usd"],
                    "base_amount_nok": row["base_amount_nok"],
                    "associated_receivable_nok": row["associated_receivable_nok"],
                    "receivable_quality": row["receivable_quality"],
                    "receivable_components": receivable_components,
                    "quality": row["ona_quality"],
                    "inputs_hash": row["ona_inputs_hash"],
                },
            }
            inputs_hash = _hash(components)
            quality_notes = (
                "FULL NAV = stored CORE NAV + receivable-aware other net assets/liabilities. "
                "Base ONA is interpolated in USD between report anchors. Bemobi distribution receivables "
                "are valued separately from entitlement/ex-date until payment and then removed as cash receives the distribution."
            )
            if row["ona_quality"] == "FORECAST_PARTIAL":
                quality_notes += " Base ONA is carried forward after the latest report and is therefore partial forecast data."
            elif row["ona_quality"] == "INTERPOLATED":
                quality_notes += " Base ONA is interpolated between reported anchors and is therefore estimated for this date."
            if row["receivable_quality"] == "ESTIMATED_GROSS":
                quality_notes += " At least one active Bemobi receivable is gross-estimated because no report-date receivable anchor exists inside its lifecycle."

            connection.execute(
                """
                INSERT INTO nav_snapshots(
                    as_of_at, nav_total_nok, nav_per_share_nok, otec_price_nok,
                    discount_pct, bemobi_value_nok, cash_estimate_nok,
                    other_net_assets_nok, shares_outstanding, calculation_version,
                    inputs_hash, status, nav_scope, components_json, quality_notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'FULL', ?, ?)
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
                    row["as_of_at"], decimal_text(full_total), decimal_text(full_per_share),
                    decimal_text(otec_price) if otec_price is not None else None,
                    decimal_text(discount) if discount is not None else None,
                    row["bemobi_value_nok"], row["cash_estimate_nok"],
                    decimal_text(ona_nok), shares, FULL_CALCULATION_VERSION,
                    inputs_hash, status, json.dumps(components, sort_keys=True, ensure_ascii=False),
                    quality_notes,
                ),
            )
            written += 1
        connection.commit()

    return {
        "calculation_version": FULL_CALCULATION_VERSION,
        "written": written,
        "from": rows[0]["as_of_at"][:10] if rows else None,
        "to": rows[-1]["as_of_at"][:10] if rows else None,
    }


def full_nav_status(database_path: str | None = None) -> dict[str, Any]:
    with get_connection(database_path) as connection:
        aggregate = connection.execute(
            """
            SELECT COUNT(*) n, MIN(substr(as_of_at,1,10)) min_date,
                   MAX(substr(as_of_at,1,10)) max_date,
                   SUM(CASE WHEN status = 'DEGRADED' THEN 1 ELSE 0 END) degraded,
                   SUM(CASE WHEN status = 'ESTIMATED' THEN 1 ELSE 0 END) estimated
            FROM nav_snapshots
            WHERE calculation_version = ? AND nav_scope = 'FULL'
            """,
            (FULL_CALCULATION_VERSION,),
        ).fetchone()
        latest = connection.execute(
            """
            SELECT as_of_at, nav_per_share_nok, otec_price_nok, discount_pct,
                   cash_estimate_nok, other_net_assets_nok, shares_outstanding,
                   status, quality_notes
            FROM nav_snapshots
            WHERE calculation_version = ? AND nav_scope = 'FULL'
            ORDER BY as_of_at DESC LIMIT 1
            """,
            (FULL_CALCULATION_VERSION,),
        ).fetchone()
        return {
            "status": "ok" if aggregate["n"] else "empty",
            "calculation_version": FULL_CALCULATION_VERSION,
            "count": aggregate["n"],
            "from": aggregate["min_date"],
            "to": aggregate["max_date"],
            "degraded": aggregate["degraded"],
            "estimated": aggregate["estimated"],
            "latest": dict(latest) if latest is not None else None,
        }

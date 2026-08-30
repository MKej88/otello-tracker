from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from app.buybacks import buyback_forecast, market_activity_status
from app.dashboard import dashboard_summary
from app.db.connection import get_connection
from app.db.migration_runner import CORE_TABLES, MIGRATIONS_DIR
from app.economic_nav import economic_nav_summary
from app.marketdata.backfill import market_data_status
from app.nav import daily_cash_status, daily_nav_status, full_nav_status, other_net_assets_status
from app.newsweb import newsweb_buyback_status, newsweb_history_status
from app.settings import settings

HISTORY_START = "2021-02-10"
NEWSWEB_HISTORY_START = "2020-01-01"
MAX_INPUT_AGE_DAYS = 7
CASH_FX_LOOKBACK_DAYS = 7
MIN_BUYBACK_ACTIVITY_DAYS = 20


def _check(
    checks: list[dict[str, Any]],
    name: str,
    ok: bool,
    *,
    details: Any = None,
    warning: bool = False,
) -> None:
    checks.append(
        {
            "name": name,
            "status": "PASS" if ok else ("WARN" if warning else "FAIL"),
            "details": details,
        }
    )


def _expected_migration() -> str | None:
    files = sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql"))
    return files[-1].name.split("_", 1)[0] if files else None


def _table_exists(connection, name: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _market_coverage(connection, symbol: str, *, price_types: tuple[str, ...] = ("CLOSE",)) -> dict[str, Any]:
    placeholders = ",".join("?" for _ in price_types)
    row = connection.execute(
        f"""
        SELECT COUNT(DISTINCT mp.trading_date) AS n,
               MIN(mp.trading_date) AS min_date,
               MAX(mp.trading_date) AS max_date
        FROM market_prices mp
        JOIN instruments i ON i.id=mp.instrument_id
        WHERE i.symbol=? AND mp.price_type IN ({placeholders})
        """,
        (symbol, *price_types),
    ).fetchone()
    return {"count": int(row["n"] or 0), "from": row["min_date"], "to": row["max_date"]}


def _fx_coverage(connection, base: str) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT COUNT(*) AS n,
               MIN(substr(observed_at,1,10)) AS min_date,
               MAX(substr(observed_at,1,10)) AS max_date
        FROM fx_rates
        WHERE base_currency=? AND quote_currency='NOK'
        """,
        (base,),
    ).fetchone()
    return {"count": int(row["n"] or 0), "from": row["min_date"], "to": row["max_date"]}


def _date_at_or_before(value: str | None, threshold: str) -> bool:
    return value is not None and value <= threshold


def _fresh_enough(value: str | None, target: date, max_age_days: int = MAX_INPUT_AGE_DAYS) -> bool:
    if not value:
        return False
    observed = date.fromisoformat(value)
    return observed <= target and (target - observed).days <= max_age_days


def cash_anchor_fx_gaps(connection) -> list[dict[str, Any]]:
    """Return reported non-NOK cash anchors that cannot be translated without guessing FX."""
    anchors_without_fx = connection.execute(
        """
        SELECT ca.as_of_date, ca.reported_currency
        FROM cash_anchors ca
        WHERE ca.anchor_type='REPORTED'
          AND ca.reported_currency <> 'NOK'
          AND NOT EXISTS (
              SELECT 1
              FROM fx_rates fr
              WHERE fr.base_currency=ca.reported_currency
                AND fr.quote_currency='NOK'
                AND substr(fr.observed_at,1,10)
                    BETWEEN date(ca.as_of_date, ?) AND ca.as_of_date
          )
        ORDER BY ca.as_of_date
        """,
        (f"-{CASH_FX_LOOKBACK_DAYS} days",),
    ).fetchall()

    gaps: list[dict[str, Any]] = []
    for anchor in anchors_without_fx:
        anchor_day = date.fromisoformat(anchor["as_of_date"])
        floor = (anchor_day - timedelta(days=CASH_FX_LOOKBACK_DAYS)).isoformat()
        gaps.append(
            {
                "anchor_date": anchor["as_of_date"],
                "currency": anchor["reported_currency"],
                "required_window": [floor, anchor["as_of_date"]],
            }
        )
    return gaps


def run_preflight(
    database_path: str,
    *,
    target_date: str | None = None,
    history_start: str = HISTORY_START,
    check_derived: bool = True,
) -> dict[str, Any]:
    """Verify that a database is safe to call production-ready."""
    target = date.fromisoformat(target_date) if target_date else date.today()
    checks: list[dict[str, Any]] = []

    if database_path != ":memory:" and not Path(database_path).exists():
        _check(checks, "database_exists", False, details={"path": database_path})
        return {
            "status": "NOT_READY",
            "ready": False,
            "target_date": target.isoformat(),
            "checks": checks,
            "blockers": [item for item in checks if item["status"] == "FAIL"],
            "warnings": [],
        }

    with get_connection(database_path) as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        _check(checks, "sqlite_integrity", integrity == "ok", details=integrity)

        schema_exists = _table_exists(connection, "schema_migrations")
        expected = _expected_migration()
        actual = None
        if schema_exists:
            row = connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1"
            ).fetchone()
            actual = row["version"] if row else None
        _check(
            checks,
            "schema_migration",
            schema_exists and actual == expected,
            details={"expected": expected, "actual": actual},
        )

        missing_tables = [name for name in CORE_TABLES if not _table_exists(connection, name)]
        _check(checks, "core_tables", not missing_tables, details={"missing": missing_tables})
        if missing_tables:
            blockers = [item for item in checks if item["status"] == "FAIL"]
            return {
                "status": "NOT_READY",
                "ready": False,
                "target_date": target.isoformat(),
                "checks": checks,
                "blockers": blockers,
                "warnings": [item for item in checks if item["status"] == "WARN"],
            }

        fixture_markers = int(
            connection.execute(
                """
                SELECT COUNT(*) AS n
                FROM source_documents
                WHERE document_type='TEST_FIXTURE'
                   OR external_id LIKE 'd1-ci-%'
                   OR url LIKE 'https://example.test/%'
                """
            ).fetchone()["n"]
        )
        _check(
            checks,
            "production_fixture_sentinel",
            fixture_markers == 0,
            details={
                "fixture_markers": fixture_markers,
                "rule": "production cutover must never contain CI/test source documents",
            },
        )

        reference_counts = {
            "cash_anchors": int(connection.execute("SELECT COUNT(*) n FROM cash_anchors WHERE anchor_type='REPORTED'").fetchone()["n"]),
            "bemobi_holdings": int(connection.execute("SELECT COUNT(*) n FROM bemobi_holdings").fetchone()["n"]),
            "otello_share_counts": int(connection.execute("SELECT COUNT(*) n FROM otello_share_counts").fetchone()["n"]),
        }
        _check(
            checks,
            "curated_reference_data",
            reference_counts["cash_anchors"] >= 2
            and reference_counts["bemobi_holdings"] >= 1
            and reference_counts["otello_share_counts"] >= 1,
            details=reference_counts,
        )

        otec_history = _market_coverage(connection, "OTEC", price_types=("CLOSE",))
        bmob3_history = _market_coverage(connection, "BMOB3", price_types=("CLOSE",))
        otec_latest = _market_coverage(connection, "OTEC", price_types=("CLOSE", "LAST"))
        brl_fx = _fx_coverage(connection, "BRL")
        usd_fx = _fx_coverage(connection, "USD")

        _check(
            checks,
            "otec_historical_prices",
            _date_at_or_before(otec_history["from"], history_start),
            details={**otec_history, "required_from": history_start},
        )
        _check(
            checks,
            "bmob3_historical_prices",
            _date_at_or_before(bmob3_history["from"], history_start),
            details={**bmob3_history, "required_from": history_start},
        )
        _check(
            checks,
            "brl_nok_historical_fx",
            _date_at_or_before(brl_fx["from"], history_start),
            details={**brl_fx, "required_from": history_start},
        )

        first_foreign_anchor = connection.execute(
            """
            SELECT MIN(as_of_date) AS first_date
            FROM cash_anchors
            WHERE anchor_type='REPORTED' AND reported_currency <> 'NOK'
            """
        ).fetchone()["first_date"]
        _check(
            checks,
            "usd_nok_historical_fx",
            first_foreign_anchor is None or _date_at_or_before(usd_fx["from"], first_foreign_anchor),
            details={**usd_fx, "required_from": first_foreign_anchor},
        )

        anchor_gaps = cash_anchor_fx_gaps(connection)
        _check(
            checks,
            "cash_anchor_fx_windows",
            not anchor_gaps,
            details={"missing_anchor_fx": anchor_gaps},
        )

        _check(
            checks,
            "otec_current_price",
            _fresh_enough(otec_latest["to"], target),
            details={**otec_latest, "max_age_days": MAX_INPUT_AGE_DAYS},
        )
        _check(
            checks,
            "bmob3_current_price",
            _fresh_enough(bmob3_history["to"], target),
            details={**bmob3_history, "max_age_days": MAX_INPUT_AGE_DAYS},
        )
        _check(
            checks,
            "brl_nok_current_fx",
            _fresh_enough(brl_fx["to"], target),
            details={**brl_fx, "max_age_days": MAX_INPUT_AGE_DAYS},
        )
        _check(
            checks,
            "usd_nok_current_fx",
            _fresh_enough(usd_fx["to"], target),
            details={**usd_fx, "max_age_days": MAX_INPUT_AGE_DAYS},
        )

    archive = newsweb_history_status(database_path)
    archive_start = archive.get("from")
    _check(
        checks,
        "newsweb_archive",
        archive.get("status") == "ok" and bool(archive_start) and str(archive_start)[:4] == "2020",
        details={**archive, "required_start_year": "2020"},
    )

    buybacks = newsweb_buyback_status(database_path)
    _check(
        checks,
        "newsweb_buybacks",
        buybacks.get("status") == "ok" and int(buybacks.get("buybacks") or buybacks.get("count") or 0) > 0,
        details=buybacks,
    )

    activity = market_activity_status(database_path)
    _check(
        checks,
        "otec_activity_history",
        int(activity.get("positive_days") or 0) >= MIN_BUYBACK_ACTIVITY_DAYS,
        details={**activity, "required_positive_days": MIN_BUYBACK_ACTIVITY_DAYS},
    )
    forecast = buyback_forecast(database_path, as_of_date=target.isoformat())
    forecast_status = str(forecast.get("status") or "UNKNOWN")
    _check(
        checks,
        "buyback_forecast_operational",
        forecast_status != "INSUFFICIENT_VOLUME_HISTORY",
        details={
            "ready": forecast.get("ready"),
            "status": forecast_status,
            "methodology_version": forecast.get("methodology_version"),
            "required_volume_days": MIN_BUYBACK_ACTIVITY_DAYS,
        },
    )
    if not forecast.get("ready") and forecast_status not in {
        "NO_ACTIVE_PROGRAM",
        "PROGRAM_EXHAUSTED",
        "INSUFFICIENT_VOLUME_HISTORY",
    }:
        _check(
            checks,
            "buyback_forecast_current_state",
            False,
            details={
                "status": forecast_status,
                "as_of_date": forecast.get("as_of_date"),
                "latest_period_end": forecast.get("latest_period_end"),
            },
            warning=True,
        )

    if check_derived:
        cash = daily_cash_status(database_path)
        core = daily_nav_status(database_path)
        ona = other_net_assets_status(database_path)
        full = full_nav_status(database_path)
        dashboard = dashboard_summary(database_path)
        economic = economic_nav_summary(database_path)

        cash_to = cash.get("to") or cash.get("last_date")
        core_to = core.get("to")
        full_to = full.get("to")
        _check(
            checks,
            "daily_cash_layer",
            cash.get("status") == "ok" and _fresh_enough(cash_to, target),
            details=cash,
        )
        _check(
            checks,
            "core_nav_layer",
            core.get("status") == "ok" and _fresh_enough(core_to, target),
            details=core,
        )
        _check(
            checks,
            "full_nav_layer",
            full.get("status") == "ok" and _fresh_enough(full_to, target),
            details=full,
        )
        _check(
            checks,
            "other_net_assets_layer",
            ona.get("status") == "ok",
            details=ona,
        )
        _check(
            checks,
            "dashboard_ready",
            bool(dashboard.get("ready")),
            details={
                "ready": dashboard.get("ready"),
                "data_status": dashboard.get("data_status"),
                "as_of_date": dashboard.get("as_of_date"),
                "model_scope": dashboard.get("model_scope"),
            },
        )
        _check(
            checks,
            "economic_nav_overlay",
            bool(economic.get("ready"))
            and economic.get("as_of_date") == dashboard.get("as_of_date"),
            details={
                "ready": economic.get("ready"),
                "reason": economic.get("reason"),
                "as_of_date": economic.get("as_of_date"),
                "dashboard_as_of_date": dashboard.get("as_of_date"),
                "nav_per_share": economic.get("nav_per_share"),
                "accounting_nav_per_share": economic.get("accounting_nav_per_share"),
                "cash_fx": economic.get("cash_fx"),
            },
        )
        _check(
            checks,
            "dashboard_quality",
            dashboard.get("data_status") not in {"DEGRADED", "ESTIMATED"},
            details={"data_status": dashboard.get("data_status"), "quality_notes": dashboard.get("quality_notes")},
            warning=True,
        )

    blockers = [item for item in checks if item["status"] == "FAIL"]
    warnings = [item for item in checks if item["status"] == "WARN"]
    ready = not blockers
    return {
        "status": "READY" if ready else "NOT_READY",
        "ready": ready,
        "target_date": target.isoformat(),
        "history_start": history_start,
        "checks": checks,
        "blockers": blockers,
        "warnings": warnings,
        "market_data": market_data_status(database_path),
        "known_expected_gaps": [
            "FULL NAV is intentionally not reconstructed before the supported ONA period.",
            "Between financial reports, cash/ONA can legitimately be FORECAST_PARTIAL or ESTIMATED; this is a warning, not a bootstrap blocker when all required inputs exist.",
            "Economic NAV is a separate investor overlay and must be current/ready before a production cutover, but it does not replace CORE/FULL NAV.",
            "A buyback program may legitimately be inactive/exhausted; missing OTEC volume history is always a blocker because it disables the forecast engine itself.",
        ],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pre-live production readiness check")
    parser.add_argument("--database", default=settings.database_path)
    parser.add_argument("--date", default=None, help="Target date; defaults to today")
    parser.add_argument("--history-start", default=HISTORY_START)
    parser.add_argument("--skip-derived", action="store_true", help="Only validate raw/reference data")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero if any blocker remains")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    result = run_preflight(
        args.database,
        target_date=args.date,
        history_start=args.history_start,
        check_derived=not args.skip_derived,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    if args.strict and not result["ready"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any

try:
    from .buyback_service import buyback_forecast
    from .dashboard_service import dashboard_summary, enrich_dashboard_summary
    from .economic_nav_investor import economic_nav_summary
except ImportError:
    from buyback_service import buyback_forecast
    from dashboard_service import dashboard_summary, enrich_dashboard_summary
    from economic_nav_investor import economic_nav_summary

HISTORY_START = "2021-02-10"
NEWSWEB_HISTORY_START_YEAR = "2020"
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


def _fresh_enough(value: str | None, target: date, max_age_days: int = MAX_INPUT_AGE_DAYS) -> bool:
    if not value:
        return False
    try:
        observed = date.fromisoformat(str(value)[:10])
    except ValueError:
        return False
    return observed <= target and (target - observed).days <= max_age_days


def _investor_nav_is_valid(
    economic: dict[str, Any],
    *,
    dashboard_as_of_date: Any,
) -> bool:
    """Require the same investor-NAV contract that production exposes to the user."""
    if not economic.get("ready") or economic.get("as_of_date") != dashboard_as_of_date:
        return False
    try:
        nav_per_share = float(economic["nav_per_share"])
        accounting_nav_per_share = float(economic["accounting_nav_per_share"])
        conservative_nav_per_share = float(economic["conservative_nav_per_share"])
    except (KeyError, TypeError, ValueError):
        return False
    values = (nav_per_share, accounting_nav_per_share, conservative_nav_per_share)
    return (
        all(math.isfinite(value) and value > 0 for value in values)
        and conservative_nav_per_share <= nav_per_share
    )


async def _market_coverage(repository, symbol: str, price_types: tuple[str, ...]) -> dict[str, Any]:
    placeholders = ",".join("?" for _ in price_types)
    row = await repository.first(
        f"""
        SELECT COUNT(DISTINCT mp.trading_date) AS n,
               MIN(mp.trading_date) AS min_date,
               MAX(mp.trading_date) AS max_date
        FROM market_prices mp
        JOIN instruments i ON i.id=mp.instrument_id
        WHERE i.symbol=? AND mp.price_type IN ({placeholders})
        """,
        (symbol, *price_types),
    )
    row = row or {}
    return {
        "count": int(row.get("n") or 0),
        "from": row.get("min_date"),
        "to": row.get("max_date"),
    }


async def _fx_coverage(repository, base: str) -> dict[str, Any]:
    row = await repository.first(
        """
        SELECT COUNT(*) AS n,
               MIN(substr(observed_at,1,10)) AS min_date,
               MAX(substr(observed_at,1,10)) AS max_date
        FROM fx_rates
        WHERE base_currency=? AND quote_currency='NOK'
        """,
        (base,),
    )
    row = row or {}
    return {
        "count": int(row.get("n") or 0),
        "from": row.get("min_date"),
        "to": row.get("max_date"),
    }


async def _cash_anchor_fx_gaps(repository) -> list[dict[str, Any]]:
    anchors = await repository.all(
        """
        SELECT as_of_date, reported_currency
        FROM cash_anchors
        WHERE anchor_type='REPORTED' AND reported_currency <> 'NOK'
        ORDER BY as_of_date
        """
    )
    gaps: list[dict[str, Any]] = []
    for anchor in anchors:
        anchor_day = date.fromisoformat(str(anchor["as_of_date"]))
        floor = (anchor_day - timedelta(days=CASH_FX_LOOKBACK_DAYS)).isoformat()
        fx = await repository.first(
            """
            SELECT substr(observed_at,1,10) AS rate_date
            FROM fx_rates
            WHERE base_currency=? AND quote_currency='NOK'
              AND substr(observed_at,1,10) BETWEEN ? AND ?
            ORDER BY observed_at DESC LIMIT 1
            """,
            (anchor["reported_currency"], floor, anchor["as_of_date"]),
        )
        if fx is None:
            gaps.append(
                {
                    "anchor_date": anchor["as_of_date"],
                    "currency": anchor["reported_currency"],
                    "required_window": [floor, anchor["as_of_date"]],
                }
            )
    return gaps


async def run_d1_preflight(
    repository,
    *,
    target_date: str,
    history_start: str = HISTORY_START,
    check_derived: bool = True,
) -> dict[str, Any]:
    """Cloudflare/D1 production-data check without SQLite-only assumptions."""
    target = date.fromisoformat(target_date)
    checks: list[dict[str, Any]] = []

    ping = await repository.first("SELECT 1 AS ok")
    _check(checks, "d1_query", bool(ping and int(ping.get("ok") or 0) == 1), details=ping)

    fixture_row = await repository.first(
        """
        SELECT COUNT(*) AS n
        FROM source_documents
        WHERE document_type='TEST_FIXTURE'
           OR external_id LIKE 'd1-ci-%'
           OR url LIKE 'https://example.test/%'
        """
    ) or {}
    fixture_markers = int(fixture_row.get("n") or 0)
    _check(
        checks,
        "production_fixture_sentinel",
        fixture_markers == 0,
        details={
            "fixture_markers": fixture_markers,
            "rule": "remote production D1 must never contain CI/test source documents",
        },
    )

    refs = await repository.first(
        """
        SELECT
          (SELECT COUNT(*) FROM cash_anchors WHERE anchor_type='REPORTED') AS cash_anchors,
          (SELECT COUNT(*) FROM bemobi_holdings) AS bemobi_holdings,
          (SELECT COUNT(*) FROM otello_share_counts) AS otello_share_counts
        """
    ) or {}
    reference_counts = {
        key: int(refs.get(key) or 0)
        for key in ("cash_anchors", "bemobi_holdings", "otello_share_counts")
    }
    _check(
        checks,
        "curated_reference_data",
        reference_counts["cash_anchors"] >= 2
        and reference_counts["bemobi_holdings"] >= 1
        and reference_counts["otello_share_counts"] >= 1,
        details=reference_counts,
    )

    otec_history = await _market_coverage(repository, "OTEC", ("CLOSE",))
    otec_latest = await _market_coverage(repository, "OTEC", ("CLOSE", "LAST"))
    bmob3 = await _market_coverage(repository, "BMOB3", ("CLOSE",))
    brl = await _fx_coverage(repository, "BRL")
    usd = await _fx_coverage(repository, "USD")

    _check(
        checks,
        "otec_historical_prices",
        bool(otec_history["from"] and str(otec_history["from"]) <= history_start),
        details={**otec_history, "required_from": history_start},
    )
    _check(
        checks,
        "bmob3_historical_prices",
        bool(bmob3["from"] and str(bmob3["from"]) <= history_start),
        details={**bmob3, "required_from": history_start},
    )
    _check(
        checks,
        "brl_nok_historical_fx",
        bool(brl["from"] and str(brl["from"]) <= history_start),
        details={**brl, "required_from": history_start},
    )

    first_foreign = await repository.first(
        """
        SELECT MIN(as_of_date) AS first_date
        FROM cash_anchors
        WHERE anchor_type='REPORTED' AND reported_currency <> 'NOK'
        """
    )
    required_usd = first_foreign.get("first_date") if first_foreign else None
    _check(
        checks,
        "usd_nok_historical_fx",
        required_usd is None or bool(usd["from"] and str(usd["from"]) <= str(required_usd)),
        details={**usd, "required_from": required_usd},
    )

    anchor_gaps = await _cash_anchor_fx_gaps(repository)
    _check(checks, "cash_anchor_fx_windows", not anchor_gaps, details={"missing_anchor_fx": anchor_gaps})

    for name, coverage in (
        ("otec_current_price", otec_latest),
        ("bmob3_current_price", bmob3),
        ("brl_nok_current_fx", brl),
        ("usd_nok_current_fx", usd),
    ):
        _check(
            checks,
            name,
            _fresh_enough(coverage["to"], target),
            details={**coverage, "max_age_days": MAX_INPUT_AGE_DAYS},
        )

    newsweb = await repository.first(
        """
        SELECT COUNT(*) AS n, MIN(substr(sd.published_at,1,10)) AS min_date,
               MAX(substr(sd.published_at,1,10)) AS max_date
        FROM source_documents sd
        JOIN sources s ON s.id=sd.source_id
        WHERE s.code='NEWSWEB' AND sd.external_id LIKE 'newsweb-message:%'
          AND sd.document_type='REGULATORY_NEWS'
        """
    ) or {}
    _check(
        checks,
        "newsweb_archive",
        int(newsweb.get("n") or 0) > 0
        and str(newsweb.get("min_date") or "")[:4] == NEWSWEB_HISTORY_START_YEAR,
        details={
            "count": int(newsweb.get("n") or 0),
            "from": newsweb.get("min_date"),
            "to": newsweb.get("max_date"),
            "required_start_year": NEWSWEB_HISTORY_START_YEAR,
        },
    )

    buybacks = await repository.first(
        "SELECT COUNT(*) AS n, MAX(trade_date) AS max_date FROM buybacks"
    ) or {}
    _check(
        checks,
        "newsweb_buybacks",
        int(buybacks.get("n") or 0) > 0,
        details={"count": int(buybacks.get("n") or 0), "to": buybacks.get("max_date")},
    )

    activity = await repository.first(
        """
        SELECT COUNT(*) AS n,
               SUM(CASE WHEN ma.volume_shares > 0 THEN 1 ELSE 0 END) AS positive_days,
               MIN(ma.trading_date) AS min_date,
               MAX(ma.trading_date) AS max_date
        FROM market_activity ma
        JOIN instruments i ON i.id=ma.instrument_id
        WHERE i.symbol='OTEC'
        """
    ) or {}
    activity_details = {
        "count": int(activity.get("n") or 0),
        "positive_days": int(activity.get("positive_days") or 0),
        "from": activity.get("min_date"),
        "to": activity.get("max_date"),
        "required_positive_days": MIN_BUYBACK_ACTIVITY_DAYS,
    }
    _check(
        checks,
        "otec_activity_history",
        activity_details["positive_days"] >= MIN_BUYBACK_ACTIVITY_DAYS,
        details=activity_details,
    )

    forecast = await buyback_forecast(repository, as_of_date=target_date)
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

    cvm = await repository.first(
        """
        SELECT COUNT(*) AS n, MAX(sd.fetched_at) AS last_fetch
        FROM source_documents sd
        JOIN sources s ON s.id=sd.source_id
        WHERE s.code='CVM' AND sd.external_id LIKE ?
        """,
        (f"cvm-ipe:{target.year}:%",),
    ) or {}
    _check(
        checks,
        "bemobi_cvm_current_year",
        int(cvm.get("n") or 0) > 0,
        details={"count": int(cvm.get("n") or 0), "last_fetch": cvm.get("last_fetch")},
        warning=True,
    )

    if check_derived:
        layers = await repository.first(
            """
            SELECT
              (SELECT MAX(estimate_date) FROM cash_daily_estimates) AS cash_to,
              (SELECT MAX(estimate_date) FROM other_net_assets_daily_estimates) AS ona_to,
              (SELECT MAX(substr(as_of_at,1,10)) FROM nav_snapshots
                 WHERE nav_scope='CORE' AND calculation_version='core-market-nav-daily-v1') AS core_to,
              (SELECT MAX(substr(as_of_at,1,10)) FROM nav_snapshots
                 WHERE nav_scope='FULL' AND calculation_version='full-market-nav-daily-v2') AS full_to
            """
        ) or {}
        for name, key in (
            ("daily_cash_layer", "cash_to"),
            ("core_nav_layer", "core_to"),
            ("full_nav_layer", "full_to"),
            ("other_net_assets_layer", "ona_to"),
        ):
            _check(
                checks,
                name,
                _fresh_enough(layers.get(key), target),
                details={"to": layers.get(key), "max_age_days": MAX_INPUT_AGE_DAYS},
            )

        summary = await dashboard_summary(repository)
        summary = await enrich_dashboard_summary(summary, repository)
        _check(
            checks,
            "dashboard_ready",
            bool(summary.get("ready")),
            details={
                "ready": summary.get("ready"),
                "data_status": summary.get("data_status"),
                "as_of_date": summary.get("as_of_date"),
                "model_scope": summary.get("model_scope"),
            },
        )

        economic = await economic_nav_summary(repository)
        _check(
            checks,
            "economic_nav_overlay",
            _investor_nav_is_valid(
                economic,
                dashboard_as_of_date=summary.get("as_of_date"),
            ),
            details={
                "ready": economic.get("ready"),
                "reason": economic.get("reason"),
                "as_of_date": economic.get("as_of_date"),
                "dashboard_as_of_date": summary.get("as_of_date"),
                "nav_per_share": economic.get("nav_per_share"),
                "accounting_nav_per_share": economic.get("accounting_nav_per_share"),
                "conservative_nav_per_share": economic.get("conservative_nav_per_share"),
                "cash_fx": economic.get("cash_fx"),
            },
        )
        _check(
            checks,
            "dashboard_quality",
            summary.get("data_status") not in {"DEGRADED", "ESTIMATED"},
            details={
                "data_status": summary.get("data_status"),
                "quality_notes": summary.get("quality_notes"),
                "market_timestamps": summary.get("market_timestamps"),
            },
            warning=True,
        )

    blockers = [item for item in checks if item["status"] == "FAIL"]
    warnings = [item for item in checks if item["status"] == "WARN"]
    return {
        "status": "READY" if not blockers else "NOT_READY",
        "ready": not blockers,
        "target_date": target_date,
        "history_start": history_start,
        "checks": checks,
        "blockers": blockers,
        "warnings": warnings,
        "known_expected_gaps": [
            "FULL NAV is intentionally unavailable before the supported ONA period.",
            "Between reports, cash/ONA may legitimately be estimated; that affects quality but does not invalidate source provenance.",
            "Economic NAV must be ready/current for full-refresh success but remains separate from accounting CORE/FULL.",
            "A buyback program may be inactive/exhausted; missing OTEC volume history is never accepted because it disables the forecast engine itself.",
        ],
    }

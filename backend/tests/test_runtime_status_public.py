from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
if str(CLOUDFLARE_SRC) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE_SRC))

from runtime_status import (  # noqa: E402
    FAST_MAX_AGE,
    FAST_RUNNING_MAX_AGE,
    FULL_MAX_AGE,
    FULL_RUNNING_MAX_AGE,
    _current_dashboard_quality,
    _dashboard_quality_reasons,
    _guard_orphaned_full_job,
    _job_freshness,
    _job_payload,
)


def test_completed_fast_job_becomes_stale_after_limit() -> None:
    now = datetime(2026, 8, 21, 10, 0, tzinfo=UTC)
    row = {
        "status": "SUCCESS",
        "started_at": "2026-08-21T07:59:00Z",
        "finished_at": "2026-08-21T08:00:00Z",
    }

    freshness = _job_freshness(
        row,
        now=now,
        completed_max_age=FAST_MAX_AGE,
        running_max_age=FAST_RUNNING_MAX_AGE,
    )

    assert freshness["stale"] is True
    assert freshness["reason"] == "too_old"
    assert freshness["age_minutes"] == 120


def test_recent_fast_job_is_current() -> None:
    now = datetime(2026, 8, 21, 10, 0, tzinfo=UTC)
    row = {
        "status": "SUCCESS",
        "started_at": "2026-08-21T09:28:00Z",
        "finished_at": "2026-08-21T09:30:00Z",
    }

    freshness = _job_freshness(
        row,
        now=now,
        completed_max_age=FAST_MAX_AGE,
        running_max_age=FAST_RUNNING_MAX_AGE,
    )

    assert freshness == {"stale": False, "age_minutes": 30, "reason": None}


def test_public_job_payload_does_not_expose_raw_exception_text() -> None:
    now = datetime(2026, 8, 21, 10, 0, tzinfo=UTC)
    row = {
        "status": "FAILED",
        "started_at": "2026-08-21T09:30:00Z",
        "finished_at": "2026-08-21T09:31:00Z",
        "records_written": 0,
        "error_message": "upstream request failed: https://example.invalid/?token=secret-value",
        "metadata_json": '{"target_date":"2026-08-20"}',
    }

    payload = _job_payload(
        row,
        now=now,
        completed_max_age=FAST_MAX_AGE,
        running_max_age=FAST_RUNNING_MAX_AGE,
    )

    assert payload["error_message"] is None
    assert payload["has_error"] is True
    assert payload["target_date"] == "2026-08-20"


def test_public_job_payload_includes_safe_nightly_summary() -> None:
    now = datetime(2026, 8, 21, 10, 0, tzinfo=UTC)
    row = {
        "status": "PARTIAL",
        "started_at": "2026-08-21T03:30:00Z",
        "finished_at": "2026-08-21T03:34:50Z",
        "records_written": 162,
        "error_message": "secret upstream detail",
        "metadata_json": (
            '{"target_date":"2026-08-20",'
            '"source_health":{"NORGES_BANK":"OK","BEMOBI_IR":"DOWN",'
            '"PRIVATE_SOURCE":"secret"},'
            '"preflight":{"ready":true,"blockers":[],"warnings":['
            '{"name":"bemobi_cvm_current_year","status":"WARN",'
            '"details":{"count":0,"private":"secret-cvm-detail"}},'
            '{"name":"private_internal_check","status":"WARN",'
            '"details":{"token":"secret-preflight-token"}}]}}'
        ),
    }

    payload = _job_payload(
        row,
        now=now,
        completed_max_age=FULL_MAX_AGE,
        running_max_age=FULL_RUNNING_MAX_AGE,
    )

    assert payload["records_written"] == 162
    assert payload["source_health"] == {
        "NORGES_BANK": "OK",
        "BEMOBI_IR": "DOWN",
    }
    assert payload["preflight"] == {
        "ready": True,
        "blocker_count": 0,
        "warning_count": 1,
        "warnings": [
            {
                "code": "bemobi_cvm_current_year",
                "message": "Bemobi / CVM: Ingen CVM-dokumenter funnet for 2026.",
            }
        ],
    }
    assert "PRIVATE_SOURCE" not in payload["source_health"]
    assert "secret-cvm-detail" not in str(payload["preflight"])
    assert "secret-preflight-token" not in str(payload["preflight"])
    assert "private_internal_check" not in str(payload["preflight"])


def test_public_job_payload_filters_normal_estimates_and_explains_actionable_warnings() -> None:
    now = datetime(2026, 8, 21, 10, 0, tzinfo=UTC)
    row = {
        "status": "SUCCESS",
        "started_at": "2026-08-21T03:30:00Z",
        "finished_at": "2026-08-21T03:34:50Z",
        "records_written": 162,
        "error_message": None,
        "metadata_json": (
            '{"target_date":"2026-08-20","preflight":{"ready":true,"blockers":[],"warnings":['
            '{"name":"dashboard_quality","status":"WARN","details":{"data_status":"ESTIMATED"}},'
            '{"name":"buyback_forecast_current_state","status":"WARN",'
            '"details":{"status":"PRIVATE_UPSTREAM_STATUS","error":"secret"}}]}}'
        ),
    }

    payload = _job_payload(
        row,
        now=now,
        completed_max_age=FULL_MAX_AGE,
        running_max_age=FULL_RUNNING_MAX_AGE,
    )

    assert payload["preflight"]["warning_count"] == 1
    assert payload["preflight"]["warnings"] == [
        {
            "code": "buyback_forecast_current_state",
            "message": "Tilbakekjøpsprognose: Prognosemotoren er ikke klar i gjeldende tilstand.",
        },
    ]
    assert "PRIVATE_UPSTREAM_STATUS" not in str(payload["preflight"])
    assert "secret" not in str(payload["preflight"])


def test_dashboard_quality_warning_ignores_normal_degraded_forecast_note() -> None:
    now = datetime(2026, 9, 5, 4, 0, tzinfo=UTC)
    notes = (
        "FULL NAV = stored CORE NAV + option-aware other net assets/liabilities. "
        "Base ONA excluding the option obligation is carried forward after the latest report "
        "and is therefore partial forecast data."
    )
    row = {
        "status": "SUCCESS",
        "started_at": "2026-09-05T03:30:00Z",
        "finished_at": "2026-09-05T03:34:00Z",
        "records_written": 100,
        "error_message": None,
        "metadata_json": json.dumps(
            {
                "target_date": "2026-09-04",
                "preflight": {
                    "ready": True,
                    "blockers": [],
                    "warnings": [
                        {
                            "name": "dashboard_quality",
                            "status": "WARN",
                            "details": {"data_status": "DEGRADED", "quality_notes": notes},
                        }
                    ],
                },
            }
        ),
    }

    payload = _job_payload(
        row,
        now=now,
        completed_max_age=FULL_MAX_AGE,
        running_max_age=FULL_RUNNING_MAX_AGE,
    )

    assert payload["preflight"]["warning_count"] == 0
    assert payload["preflight"]["warnings"] == []


def test_dashboard_quality_reasons_ignore_normal_estimation_states() -> None:
    reasons = _dashboard_quality_reasons(
        {
            "data_status": "DEGRADED",
            "cash_quality": "FORECAST_PARTIAL",
            "share_count_quality": "POTENTIALLY_STALE",
            "ona_quality": "FORECAST_PARTIAL",
        }
    )

    assert reasons == []


def test_dashboard_quality_reasons_keep_real_quality_problems() -> None:
    reasons = _dashboard_quality_reasons(
        {
            "data_status": "DEGRADED",
            "cash_quality": "FORECAST_PARTIAL",
            "cash_calibration_quality": "HIGH_RESIDUAL",
            "share_count_quality": "POTENTIALLY_STALE",
            "ona_quality": "FORECAST_PARTIAL",
            "receivable_quality": "ESTIMATED_GROSS",
        }
    )

    assert reasons == [
        "Kontantestimatet ligger i en periode med høy avstemmingsrest og har lavere kvalitet.",
        "Minst én Bemobi-fordring er bruttoestimert fordi det mangler et rapportankre i perioden.",
    ]


class _QualityRepository:
    async def first(self, query: str, params=()):
        if "nav_scope='FULL'" in query:
            return {
                "as_of_at": "2026-09-04T23:59:59Z",
                "status": "DEGRADED",
                "quality_notes": "safe stored note",
                "components_json": json.dumps(
                    {
                        "other_net_assets": {
                            "quality": "FORECAST_PARTIAL",
                            "receivable_quality": "NONE",
                            "option_liability": {"quality": "FORECAST_MARK_TO_MARKET"},
                        }
                    }
                ),
            }
        if "nav_scope='CORE'" in query:
            return {
                "status": "DEGRADED",
                "components_json": json.dumps(
                    {
                        "cash": {"quality": "FORECAST_PARTIAL", "calibration_quality": None},
                        "otec": {"share_count_quality": "CURRENT_KNOWN"},
                    }
                ),
            }
        raise AssertionError(f"unexpected query: {query} {params}")


def test_current_dashboard_quality_keeps_raw_status_but_suppresses_normal_estimate_warning() -> None:
    quality = asyncio.run(_current_dashboard_quality(_QualityRepository()))

    assert quality == {
        "available": True,
        "status": "OK",
        "data_status": "DEGRADED",
        "as_of_date": "2026-09-04",
        "reasons": [],
    }


def _running_full_payload(now: datetime) -> tuple[dict, dict]:
    row = {
        "status": "RUNNING",
        "started_at": "2026-08-22T03:35:43Z",
        "finished_at": None,
        "records_written": 0,
        "error_message": None,
        "metadata_json": '{"target_date":"2026-08-21"}',
    }
    payload = _job_payload(
        row,
        now=now,
        completed_max_age=FULL_MAX_AGE,
        running_max_age=FULL_RUNNING_MAX_AGE,
    )
    return row, payload


def test_running_full_job_stays_running_with_matching_active_writer_lease() -> None:
    now = datetime(2026, 8, 22, 4, 0, tzinfo=UTC)
    row, payload = _running_full_payload(now)
    guarded = _guard_orphaned_full_job(
        payload,
        row,
        {
            "value": "full:2026-08-21:workflow-instance|2026-08-22T06:36:27Z",
            "updated_at": "2026-08-22T03:36:27Z",
        },
        now=now,
    )

    assert guarded["status"] == "RUNNING"
    assert guarded["stale"] is False
    assert guarded["reason"] is None


def test_running_full_job_is_failed_when_writer_lease_is_missing_or_expired() -> None:
    now = datetime(2026, 8, 22, 7, 0, tzinfo=UTC)
    row, payload = _running_full_payload(now)

    missing = _guard_orphaned_full_job(payload, row, None, now=now)
    expired = _guard_orphaned_full_job(
        payload,
        row,
        {"value": "full:2026-08-21:workflow-instance|2026-08-22T06:36:27Z"},
        now=now,
    )

    for guarded in (missing, expired):
        assert guarded["status"] == "FAILED"
        assert guarded["stale"] is True
        assert guarded["reason"] == "writer_lease_inactive"
        assert guarded["has_error"] is True
        assert guarded["error_message"] is None

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
CLOUDFLARE_TOOLS = ROOT / "cloudflare" / "tools"
for path in (CLOUDFLARE_SRC, CLOUDFLARE_TOOLS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import performance_repository  # noqa: E402
from render_production_config import WORKER_SUBREQUEST_LIMIT, render_config  # noqa: E402
from status_email import _finalize_failed_job, build_status_email  # noqa: E402


def _base_config() -> dict:
    return json.loads(
        (ROOT / "cloudflare" / "wrangler.jsonc").read_text(encoding="utf-8")
    )


def _render(**overrides) -> dict:
    values = {
        "worker_name": "otello-tracker",
        "d1_database_id": "00000000-0000-0000-0000-000000000123",
        "d1_database_name": "otello-nav",
        "r2_bucket_name": "otello-source-archive",
        "custom_domain": "nav.example.com",
        "status_email_to": "owner@example.net",
        "status_email_from": "status@nav.example.com",
        "public_url": "https://nav.example.com/",
        "deployment_revision": "0123456789abcdef0123456789abcdef01234567",
    }
    values.update(overrides)
    return render_config(_base_config(), **values)


def test_success_email_contains_operational_and_investor_status() -> None:
    message = build_status_email(
        {
            "status": "SUCCESS",
            "target_date": "2026-08-21",
            "records_written": 17,
            "source_health": {
                "NORGES_BANK": "OK",
                "B3": "OK",
                "CVM": "OK",
                "BEMOBI_IR": "OK",
                "NEWSWEB": "OK",
                "EURONEXT": "OK",
            },
            "preflight": {"ready": True, "blockers": [], "warnings": []},
            "critical_errors": [],
        },
        economic={
            "ready": True,
            "as_of_date": "2026-08-21",
            "nav_per_share": 31.42,
            "discount_pct": 17.8,
            "conservative_nav_per_share": 30.11,
        },
        started_at="2026-08-22T03:35:00Z",
        finished_at="2026-08-22T03:36:14Z",
        public_url="https://nav.example.com/",
    )

    assert message["subject"] == "Otello Tracker – nattkjøring OK – 2026-08-21"
    assert "Kjøretid: 1 min 14 sek" in message["text"]
    assert "Datakilder: 6/6 OK" in message["text"]
    assert "Økonomisk NAV: 31,42 kr/aksje" in message["text"]
    assert "Rabatt: 17,8 %" in message["text"]
    assert "Dashboard: https://nav.example.com/" in message["text"]


def test_failure_email_surfaces_critical_error_without_nav() -> None:
    message = build_status_email(
        {
            "status": "FAILED",
            "target_date": "2026-08-21",
            "source_health": {"NEWSWEB": "DOWN"},
            "critical_errors": [{"step": "newsweb", "error": "source unavailable"}],
            "preflight": {
                "ready": False,
                "blockers": [{"name": "source"}],
                "warnings": [],
            },
        },
        economic={"ready": False, "reason": "missing_full_nav_row"},
    )

    assert "nattkjøring FEILET" in message["subject"]
    assert "NewsWeb: DOWN" in message["text"]
    assert "Preflight: FEILET" in message["text"]
    assert "newsweb: source unavailable" in message["text"]
    assert "Investor-NAV: ikke klar" in message["text"]


def test_production_email_binding_is_required_and_restricted() -> None:
    with pytest.raises(ValueError, match="påkrevd for produksjon"):
        _render(status_email_to=None, status_email_from=None)

    config = _render()
    assert config["send_email"] == [
        {
            "name": "STATUS_EMAIL",
            "destination_address": "owner@example.net",
            "allowed_sender_addresses": ["status@nav.example.com"],
        }
    ]
    assert config["vars"]["STATUS_EMAIL_TO"] == "owner@example.net"
    assert config["vars"]["STATUS_EMAIL_FROM"] == "status@nav.example.com"
    assert config["vars"]["PUBLIC_URL"] == "https://nav.example.com"
    assert (
        config["vars"]["DEPLOYMENT_REVISION"]
        == "0123456789abcdef0123456789abcdef01234567"
    )


def test_worker_dev_config_can_still_omit_status_email() -> None:
    config = _render(
        custom_domain=None,
        status_email_to=None,
        status_email_from=None,
        public_url=None,
        deployment_revision=None,
    )
    assert config["workers_dev"] is True
    assert "send_email" not in config


def test_production_worker_keeps_bounded_headroom_for_historical_rebuild() -> None:
    config = _render()
    assert WORKER_SUBREQUEST_LIMIT == 50000
    assert config["limits"] == {"cpu_ms": 60000, "subrequests": 50000}


def test_production_email_configuration_requires_sender_and_recipient_together() -> (
    None
):
    with pytest.raises(ValueError, match="må settes sammen"):
        _render(status_email_to="owner@example.net", status_email_from=None)

    with pytest.raises(ValueError, match="må settes sammen"):
        _render(status_email_to=None, status_email_from="status@nav.example.com")


def test_failed_workflow_job_is_finalized_even_without_email_binding(
    monkeypatch,
) -> None:
    calls: list[dict] = []

    class _Repository:
        def __init__(self, database) -> None:
            assert database == "DB"

        async def finish_job(self, job_id, **kwargs):
            calls.append({"job_id": job_id, **kwargs})

    monkeypatch.setattr(
        performance_repository, "PerformanceD1WriteRepository", _Repository
    )
    result = asyncio.run(
        _finalize_failed_job(
            SimpleNamespace(DB="DB"),
            {
                "status": "FAILED",
                "job_id": 141,
                "target_date": "2026-08-21",
                "records_written": 0,
                "critical_errors": [
                    {
                        "step": "workflow",
                        "error": "Too many API requests by single Worker invocation",
                    }
                ],
            },
        )
    )

    assert result["status"] == "finalized"
    assert len(calls) == 1
    assert calls[0]["job_id"] == 141
    assert calls[0]["status"] == "FAILED"
    assert calls[0]["records_written"] == 0
    assert "Too many API requests" in calls[0]["error_message"]
    assert calls[0]["metadata"]["workflow_exception"] is True


def test_controlled_failed_result_is_not_finalized_twice(monkeypatch) -> None:
    calls: list[dict] = []

    class _Repository:
        def __init__(self, database) -> None:
            calls.append({"database": database})

    monkeypatch.setattr(
        performance_repository, "PerformanceD1WriteRepository", _Repository
    )
    result = asyncio.run(
        _finalize_failed_job(
            SimpleNamespace(DB="DB"),
            {
                "status": "FAILED",
                "job_id": 142,
                "target_date": "2026-08-21",
                "source_results": {},
                "critical_errors": [{"step": "preflight", "error": "1 blocker"}],
            },
        )
    )

    assert result == {"status": "skipped", "reason": "already_finalized"}
    assert calls == []


def test_html_report_escapes_errors_and_exposes_noncritical_cache_failure():
    message = build_status_email(
        {
            "status": "SUCCESS",
            "job_id": 123,
            "target_date": "2026-10-16",
            "dashboard_hot_snapshot": {
                "status": "error",
                "error": '<script>alert("x")</script> token=private-value',
            },
            "archive": {"status": "ok"},
            "nav": {"status": "ok"},
        },
        started_at="2026-10-17T03:35:00Z",
        finished_at="2026-10-17T03:40:00Z",
        public_url="https://otellotracker.com/",
    )
    assert "OK med avvik" in message["subject"]
    assert "17.10.2026 kl. 05:35 CEST" in message["text"]
    assert "Dashboard-cache: FEILET" in message["text"]
    assert "Nettsiden kan vise eldre data" in message["text"]
    assert "private-value" not in message["text"] + message["html"]
    assert "<script>" not in message["html"]
    assert "&lt;script&gt;" in message["html"]
    assert '<html lang="nb">' in message["html"]
    assert 'href="https://otellotracker.com/"' in message["html"]
    assert "Separate GitHub-kontroller" in message["text"]


def test_all_error_lists_warnings_and_auxiliary_failures_are_reported():
    message = build_status_email(
        {
            "status": "FAILED",
            "critical_errors": [{"step": "nav", "error": "missing input"}],
            "errors": [
                {"step": "nav", "error": "missing input"},
                {"step": "archive", "error": "R2 failed"},
            ],
            "preflight": {
                "ready": False,
                "checks": [{"name": "fx", "status": "FAIL"}],
                "blockers": [{"name": "fx", "details": "missing USD/NOK"}],
                "warnings": [{"name": "news", "details": "old date"}],
            },
            "estimated_nav_history": {
                "status": "error",
                "error": "history unavailable",
            },
        }
    )
    assert message["text"].count("- nav: missing input") == 1
    for detail in (
        "R2 failed",
        "missing USD/NOK",
        "old date",
        "history unavailable",
        "Datakontroller bestått: 0/1",
    ):
        assert detail in message["text"]


def test_unexecuted_checks_are_not_reported_as_success_and_urls_are_restricted():
    message = build_status_email({"status": "FAILED"}, public_url="javascript:alert(1)")
    assert "Dashboard-cache: ikke rapportert" in message["text"]
    assert "javascript:" not in message["html"]
    assert "href=" not in message["html"]


def test_email_has_plaintext_and_html_in_one_send(monkeypatch):
    import status_email

    calls = []

    class Binding:
        async def send(self, payload):
            calls.append(payload)
            return SimpleNamespace(messageId="test-message")

    class Repository:
        def __init__(self, database):
            pass

    async def economic(repository):
        return {"ready": False, "reason": "test"}

    monkeypatch.setattr(performance_repository, "PerformanceD1Repository", Repository)
    import economic_nav_investor

    monkeypatch.setattr(economic_nav_investor, "economic_nav_summary", economic)
    monkeypatch.setitem(
        sys.modules, "js", SimpleNamespace(Object=SimpleNamespace(fromEntries=None))
    )
    monkeypatch.setitem(
        sys.modules,
        "pyodide.ffi",
        SimpleNamespace(to_js=lambda payload, **kwargs: payload),
    )
    env = SimpleNamespace(
        DB="DB",
        STATUS_EMAIL_TO="owner@example.net",
        STATUS_EMAIL_FROM="status@example.net",
        STATUS_EMAIL=Binding(),
    )
    result = asyncio.run(
        status_email.send_full_refresh_status_email(env, {"status": "SUCCESS"})
    )
    assert result["status"] == "sent"
    assert len(calls) == 1
    assert calls[0]["text"] and calls[0]["html"]


@pytest.mark.parametrize(
    "details",
    [
        {
            "data_status": "DEGRADED",
            "quality_notes": "Base ONA is partial forecast data using latest reported risk-free-rate/volatility.",
        },
        {"data_status": "ESTIMATED", "cash_quality": "ANCHORED_ESTIMATE"},
    ],
)
def test_expected_nav_estimates_are_information_not_email_incidents(details) -> None:
    warning = {"name": "dashboard_quality", "status": "WARN", "details": details}
    result = {
        "status": "SUCCESS",
        "target_date": "2026-10-18",
        "preflight": {"ready": True, "blockers": [], "warnings": [warning]},
    }
    original = json.dumps(result, sort_keys=True)
    message = build_status_email(result)
    assert "nattkjøring OK –" in message["subject"]
    assert "med avvik" not in message["subject"]
    for body in (message["text"], message["html"]):
        assert "Modellinformasjon" in body
        assert "dashboard_quality" not in body
        assert "Ingen rapporterte feil eller advarsler" in body
    assert "Advarsler: 0" in message["text"]
    assert json.dumps(result, sort_keys=True) == original


@pytest.mark.parametrize(
    "warning",
    [
        {
            "name": "dashboard_quality",
            "status": "WARN",
            "details": {
                "data_status": "DEGRADED",
                "cash_quality": "FORECAST_PARTIAL",
                "cash_calibration_quality": "HIGH_RESIDUAL",
            },
        },
        {
            "name": "dashboard_quality",
            "status": "WARN",
            "details": {
                "data_status": "ESTIMATED",
                "receivable_quality": "ESTIMATED_GROSS",
            },
        },
        {
            "name": "dashboard_quality",
            "status": "WARN",
            "details": {"data_status": "DEGRADED"},
        },
        {"name": "bemobi_cvm_current_year", "status": "WARN", "details": {"count": 0}},
        {"name": "new_unknown_check", "status": "WARN", "details": {}},
    ],
)
def test_real_and_unknown_warnings_remain_email_incidents(warning) -> None:
    expected = {
        "name": "dashboard_quality",
        "status": "WARN",
        "details": {"data_status": "ESTIMATED"},
    }
    message = build_status_email(
        {
            "status": "SUCCESS",
            "target_date": "2026-10-18",
            "preflight": {
                "ready": True,
                "blockers": [],
                "warnings": [expected, warning],
            },
        }
    )
    assert "OK med avvik" in message["subject"]
    assert "Advarsler: 1" in message["text"]
    assert warning["name"] in message["text"]
    assert warning["name"] in message["html"]


def test_model_warning_filter_does_not_remove_blockers() -> None:
    blocker = {
        "name": "dashboard_quality",
        "status": "FAIL",
        "details": {"data_status": "ESTIMATED"},
    }
    message = build_status_email(
        {
            "status": "FAILED",
            "preflight": {"ready": False, "blockers": [blocker], "warnings": []},
        }
    )
    assert "FEILET" in message["subject"]
    assert "Blokkeringer: 1" in message["text"]
    assert "dashboard_quality" in message["text"]

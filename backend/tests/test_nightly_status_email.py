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


@pytest.mark.parametrize(
    "market_status,ready,critical,job_status,expected_info",
    [
        ("MIXED", True, [], "SUCCESS", True),
        ("STALE", True, [], "SUCCESS", False),
        ("UNKNOWN", True, [], "SUCCESS", False),
        ("MIXED", False, [], "SUCCESS", False),
        ("MIXED", True, ["NAV failure"], "SUCCESS", False),
        ("MIXED", True, [], "PARTIAL", False),
    ],
)
def test_structured_nav_quality_respects_operational_health(
    market_status, ready, critical, job_status, expected_info
) -> None:
    result = {
        "status": job_status,
        "target_date": "2026-11-24",
        "critical_errors": critical,
        "preflight": {
            "ready": ready,
            "blockers": [],
            "warnings": [
                {
                    "name": "dashboard_quality",
                    "status": "WARN",
                    "details": {
                        "data_status": "DEGRADED",
                        "cash_quality": "FORECAST_PARTIAL",
                        "market_timestamps": {"status": market_status},
                        "quality_notes": "FULL NAV methodology only",
                    },
                }
            ],
        },
    }
    original = json.dumps(result, sort_keys=True)
    message = build_status_email(result)
    assert ("Modellinformasjon" in message["text"]) == expected_info
    assert ("dashboard_quality" in message["text"]) != expected_info
    assert json.dumps(result, sort_keys=True) == original


def test_nav_warning_contains_structured_quality_evidence() -> None:
    message = build_status_email(
        {
            "status": "SUCCESS",
            "preflight": {
                "ready": True,
                "blockers": [],
                "warnings": [
                    {
                        "name": "dashboard_quality",
                        "status": "WARN",
                        "details": {
                            "data_status": "DEGRADED",
                            "cash_quality": "FORECAST_PARTIAL",
                            "cash_calibration_quality": "HIGH_RESIDUAL",
                        },
                    }
                ],
            },
        }
    )
    assert "cash_calibration_quality=HIGH_RESIDUAL" in message["text"]
    assert "dashboard_quality" in message["text"]
    assert "OK med avvik" in message["subject"]


def test_preflight_model_information_is_preserved_in_email() -> None:
    result = {
        "status": "SUCCESS",
        "target_date": "2026-11-25",
        "preflight": {
            "ready": True,
            "blockers": [],
            "warnings": [],
            "checks": [
                {
                    "name": "dashboard_quality",
                    "status": "PASS",
                    "details": {"classification": "MODEL_INFO", "data_status": "ESTIMATED"},
                }
            ],
        },
    }
    original = json.dumps(result, sort_keys=True)
    message = build_status_email(result)
    assert "Modellinformasjon" in message["text"]
    assert "Advarsler: 0" in message["text"]
    assert "med avvik" not in message["subject"]
    assert json.dumps(result, sort_keys=True) == original


def test_compact_email_prioritizes_actual_failure_and_omits_successful_source_steps():
    result = {
        "status": "FAILED", "job_id": 42, "target_date": "2026-11-25",
        "source_health": {"B3": "OK", "CVM": "OK", "NEWSWEB": "OK"},
        "source_results": {"b3": {"status": "ok", "rows_written": 10}, "cvm": {"status": "ok"}},
        "critical_errors": [{"step": "workflow", "error": "Traceback (most recent call last):\n  File long_path\nRuntimeError: refresh writer lease lost at history"}],
        "nav": {"status": "ok"},
    }
    message = build_status_email(result, economic={"ready": True, "nav_per_share": 22.5},
                                 public_url="https://otellotracker.com")
    body = message["text"]
    assert "refresh writer lease lost at history" in body
    assert "Traceback" not in body and "long_path" not in body
    assert body.index("Avvik og oppfølging") < body.index("Kontrollstatus")
    assert "Kildesteg" not in body and "B3: OK" not in body
    assert "Investor-NAV: ikke klar" in body
    assert "22,50 kr/aksje" not in body
    assert "https://github.com/MKej88/otello-tracker/issues/164" in message["html"]
    assert "https://github.com/MKej88/otello-tracker/actions" in body


def test_history_cache_and_investor_cache_failures_are_not_hidden_by_success():
    result = {
        "status": "SUCCESS",
        "estimated_nav_history": {
            "complete": True, "retry": {"pending": 2},
            "period_cache": {"status": "partial", "written": 5,
                             "failures": [{"period_key": "1y", "reason": "memory limit"}]},
        },
        "investor_snapshots": {"status": "partial", "components": {
            "bemobi_consensus": {"status": "error", "error_type": "TimeoutError"},
        }},
    }
    message = build_status_email(result)
    assert "OK med avvik" in message["subject"]
    for body in (message["text"], message["html"]):
        assert "5/6" in body and "1y: memory limit" in body
        assert "2 historikkpunkter" in body and "bemobi_consensus" in body


def test_healthy_report_is_short_and_does_not_repeat_successful_source_details():
    result = {"status": "SUCCESS", "source_health": {"B3": "OK", "CVM": "OK"},
              "source_results": {"b3": {"status": "ok"}, "cvm": {"status": "ok"}},
              "nav": {"status": "ok"}, "dashboard_hot_snapshot": {"status": "ok"},
              "estimated_nav_history": {"complete": True, "retry": {"pending": 0},
                                        "period_cache": {"status": "ok", "written": 6}},
              "archive": {"status": "ok"}, "investor_snapshots": {"status": "ok"},
              "preflight": {"ready": True, "blockers": [], "warnings": []}}
    message = build_status_email(result, economic={"ready": True, "nav_per_share": 22.5, "discount_pct": 25})
    body = message["text"]
    assert len(body.splitlines()) <= 23
    assert "Datakilder: 2/2 OK" in body and "Periodecache: 6/6" in body
    assert "NAV-historikk: OK" in body and "Kildesteg" not in body
    assert "B3: OK" not in body and "Life360" not in body
    assert "Ingen rapporterte feil eller advarsler" in body


def test_history_queue_email_reports_retry_result_and_full_width_incident():
    message = build_status_email({
        "status": "SUCCESS",
        "estimated_nav_history": {"complete": True,
            "period_cache": {"status": "ok", "written": 6},
            "retry": {"pending": 250, "attempted": 10, "written": 0,
                      "failures": [{"date": "2025-01-02", "reason": "missing_option_inputs"}]}},
    })
    assert "250 historikkpunkter" in message["text"]
    assert "behandlet 10, løst 0" in message["text"]
    assert "missing_option_inputs" in message["html"]
    assert '<div style="font-weight:bold;margin-bottom:4px">NAV-historikk</div>' in message["html"]
    assert 'colspan="2" style="padding:10px 0' in message["html"]


def test_new_html_prioritizes_critical_incidents_and_investor_cards():
    message = build_status_email({
        "status": "PARTIAL",
        "target_date": "2026-11-28",
        "job_id": 42,
        "source_health": {"B3": "OK", "CVM": "DEGRADED"},
        "errors": [{"step": "archive", "error": "Arkiv ikke bekreftet"}],
        "critical_errors": [{"step": "nav", "error": "NAV må kontrolleres"}],
        "preflight": {
            "ready": False,
            "blockers": [{"name": "fx", "details": "Valutagrunnlag mangler"}],
            "warnings": [{"name": "news", "details": "Kilde forsinket"}],
        },
        "nav": {"status": "error"},
    }, economic={
        "ready": True, "as_of_date": "2026-11-27", "nav_per_share": 24.95,
        "conservative_nav_per_share": 23.11, "discount_pct": 20.1,
    }, public_url="https://otellotracker.com")
    html = message["html"]
    assert html.index("NAV må kontrolleres") < html.index("Arkiv ikke bekreftet")
    assert html.index("Valutagrunnlag mangler") < html.index("Arkiv ikke bekreftet")
    assert html.index("Avvik og oppfølging") < html.index("Investor-NAV") < html.index("Kontrollstatus")
    assert "Kritisk" in html and "Oppfølging / mulig konsekvens" in html
    assert "#fdecec" in html and "#fff3dc" in html and "#eaf2fc" in html
    assert "24,95 kr" in html and "Konservativ NAV" in html
    assert "NAV-dato: 2026-11-27" in html
    assert "Separate GitHub-kontroller" in html
    assert "Datakilder OK" in html and "1/2" in html


def test_new_email_only_reports_measured_resources():
    result = {
        "status": "SUCCESS",
        "records_written": 1234,
        "source_results": {
            "cvm": {"status": "ok", "repository": {
                "d1_operations": 3, "d1_row_meta_operations": 3,
                "d1_rows_read": 1000, "d1_rows_written": 12}},
            "b3": {"status": "ok", "repository": {
                "d1_operations": 3, "d1_row_meta_operations": 2,
                "d1_rows_read": None, "d1_rows_written": None}},
            "bemobi_translation": {"status": "ok", "completed": 1, "failed": 0,
                "queue": {"pending": 3, "failed": 0},
                "diagnostics": [{"ai_provider_calls": 2, "parts_reused": 6,
                                 "summary_checkpoints_reused": 1}]},
        },
        "archive": {"status": "skipped", "reason": "weekly_or_month_end_only"},
    }
    original = json.dumps(result, sort_keys=True)
    message = build_status_email(result)
    for body in (message["text"], message["html"]):
        assert "Ressursforbruk og dokumenter" in body
        assert "1 steg: 1 000 rader lest / 12 skrevet" in body
        assert "ikke totalt" in body
        assert "AI-kall i dokumentbehandling" in body
        assert "Gjenbrukte sammendrag" in body
        assert "Oversettelseskø" in body
        assert "Ikke planlagt (søndag og månedsslutt)" in body
    assert json.dumps(result, sort_keys=True) == original
    minimal = build_status_email({"status": "SUCCESS"})["html"]
    assert "Ukjent" in minimal
    assert "Ressursforbruk og dokumenter" not in minimal
    assert "D1 – målte kildesteg" not in minimal

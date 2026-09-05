from __future__ import annotations

import asyncio
import sys
from pathlib import Path

WORKER_SRC = Path(__file__).resolve().parents[2] / "cloudflare" / "src"
if str(WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(WORKER_SRC))

import brazil_calendar_expectations as calendar_expectations  # noqa: E402
from brazil_calendar_expectations import (  # noqa: E402
    _monthly_expectation,
    _quarter_reference,
    _quarterly_expectation,
    _selic_expectation,
)
from brazil_dashboard_v2 import (  # noqa: E402
    _annotate_market_consensus,
    _fill_annual_focus_proxies,
)


def test_monthly_focus_is_used_for_ipca_reference_month() -> None:
    event = {
        "date": "2026-09-11",
        "name": "IPCA",
        "kind": "inflation",
        "reference": "aug. 2026",
    }
    rows = [
        {
            "Indicador": "IPCA",
            "Data": "2026-08-28",
            "DataReferencia": "08/2026",
            "Mediana": 0.31,
            "numeroRespondentes": 95,
        }
    ]

    result = _monthly_expectation(event, rows)

    assert result is not None
    assert result["value"] == 0.31
    assert result["event_consensus"] is True
    assert result["provider"] == "BCB Focus"
    assert "08/26" in result["label"]


def test_copom_uses_focus_expectation_for_exact_meeting() -> None:
    event = {
        "date": "2026-09-16",
        "name": "Copom rentebeslutning",
        "kind": "copom",
    }
    rows = [
        {
            "Indicador": "Selic",
            "Data": "2026-08-28",
            "Reuniao": "R6/2026",
            "Mediana": 14.5,
            "numeroRespondenter": 88,
        },
        {
            "Indicador": "Selic",
            "Data": "2026-08-28",
            "Reuniao": "R7/2026",
            "Mediana": 14.0,
        },
    ]

    result = _selic_expectation(event, rows)

    assert result is not None
    assert result["value"] == 14.5
    assert "R6/2026" in result["label"]


def test_quarterly_gdp_reference_is_parsed_and_matched() -> None:
    assert _quarter_reference("2026 Q2") == (2026, 2)
    assert _quarter_reference("2/2026") == (2026, 2)

    event = {
        "date": "2026-09-01",
        "name": "BNP Q2",
        "kind": "gdp",
        "reference": "2026 Q2",
    }
    rows = [
        {
            "Indicador": "PIB Total",
            "Data": "2026-06-30",
            "DataReferencia": "2/2026",
            "Mediana": 0.6,
            "numeroRespondentes": 72,
        }
    ]

    result = _quarterly_expectation(event, rows)

    assert result is not None
    assert result["value"] == 0.6
    assert result["label"] == "Focus BNP Q2 2026"


def test_gdp_enrichment_fetches_target_quarter_with_long_lookback(monkeypatch) -> None:
    calls: dict[str, dict] = {}

    async def fake_fetch_endpoint(endpoint: str, **kwargs):
        calls[endpoint] = kwargs
        if endpoint == "ExpectativasMercadoTrimestrais":
            return [
                {
                    "Indicador": "PIB Total",
                    "Data": "2026-06-30",
                    "DataReferencia": "2/2026",
                    "Mediana": 0.2,
                    "numeroRespondentes": 61,
                }
            ]
        return []

    monkeypatch.setattr(calendar_expectations, "_fetch_endpoint", fake_fetch_endpoint)
    events = [
        {
            "date": "2026-09-01",
            "name": "Økonomisk vekst (BNP) Q2",
            "kind": "gdp",
            "reference": "2026 Q2",
        }
    ]

    enriched, status = asyncio.run(
        calendar_expectations.enrich_calendar_expectations(events, as_of_date="2026-09-01")
    )

    quarterly_call = calls["ExpectativasMercadoTrimestrais"]
    assert quarterly_call["start_date"] == "2026-03-05"
    assert quarterly_call["end_date"] == "2026-09-01"
    assert quarterly_call["references"] == ["2/2026"]
    assert enriched[0]["expectation"]["value"] == 0.2
    assert enriched[0]["expectation"]["event_consensus"] is True
    assert status["quarterly"]["lookback_days"] == 180


def test_focus_expectation_is_marked_as_market_consensus() -> None:
    events = _annotate_market_consensus(
        [
            {
                "name": "IPCA",
                "kind": "inflation",
                "expectation": {
                    "event_consensus": True,
                    "provider": "BCB Focus",
                    "value": 0.31,
                },
            }
        ]
    )

    consensus = events[0]["market_consensus"]
    assert consensus["available"] is True
    assert consensus["ingested"] is True
    assert consensus["coverage"] == "BCB_FOCUS_EVENT"
    assert consensus["provider"] == "BCB Focus"


def test_investing_expectation_is_marked_as_primary_market_consensus() -> None:
    events = _annotate_market_consensus(
        [
            {
                "name": "BNP Q2",
                "kind": "gdp",
                "expectation": {
                    "event_consensus": True,
                    "provider": "Investing.com",
                    "value": 0.4,
                },
            }
        ]
    )

    consensus = events[0]["market_consensus"]
    assert consensus["available"] is True
    assert consensus["ingested"] is True
    assert consensus["coverage"] == "INVESTING_EVENT"
    assert consensus["provider"] == "Investing.com"


def test_annual_focus_proxy_is_not_presented_as_event_consensus() -> None:
    events = _annotate_market_consensus(
        [
            {
                "name": "IPCA",
                "kind": "inflation",
                "expectation": {
                    "event_consensus": False,
                    "label": "Focus 2026 IPCA (år)",
                    "value": 4.2,
                    "unit": "%",
                },
            }
        ]
    )

    event = events[0]
    assert event["expectation"]["value"] == 4.2
    assert event["market_consensus"] == {
        "available": True,
        "ingested": True,
        "coverage": "BCB_FOCUS_ANNUAL_PROXY",
        "provider": "BCB Focus",
        "note": (
            "Et årsestimat fra BCB Focus finnes som bakgrunn, men brukes ikke som "
            "hendelseskonsensus for denne publiseringen."
        ),
    }


def test_resilient_annual_focus_fills_empty_calendar_expectation() -> None:
    events = _fill_annual_focus_proxies(
        [
            {
                "date": "2026-09-11",
                "name": "IPCA",
                "kind": "inflation",
            }
        ],
        {"ipca": {"2026": {"median": 4.2, "survey_date": "2026-08-28"}}},
    )

    assert events[0]["expectation"] == {
        "label": "Focus 2026 IPCA (år)",
        "value": 4.2,
        "unit": "%",
        "survey_date": "2026-08-28",
        "event_consensus": False,
    }


def test_pms_pmc_and_ibc_br_report_missing_current_investing_forecast() -> None:
    events = _annotate_market_consensus(
        [
            {"name": "Tjenesteaktivitet (PMS)", "kind": "services"},
            {"name": "Detaljhandel (PMC)", "kind": "retail"},
            {"name": "IBC-Br", "kind": "activity"},
        ]
    )

    for event in events:
        consensus = event["market_consensus"]
        assert consensus["available"] is True
        assert consensus["ingested"] is False
        assert consensus["coverage"] == "EXTERNAL_MARKET_CONSENSUS_NOT_INGESTED"
        assert consensus["provider"] == "Investing.com"
        assert "Forecast" in consensus["note"]

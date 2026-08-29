from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

WORKER_SRC = Path(__file__).resolve().parents[2] / "cloudflare" / "src"
if str(WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(WORKER_SRC))

from brazil_calendar_expectations import (  # noqa: E402
    _monthly_expectation,
    _quarter_reference,
    _quarterly_expectation,
    _selic_expectation,
    enrich_calendar_expectations,
)
from brazil_dashboard_v2 import (  # noqa: E402
    _annotate_market_consensus,
    _prepare_calendar_rows,
)


class _Response:
    ok = True
    status = 200

    def __init__(self, payload: object) -> None:
        self._body = json.dumps(payload).encode()

    async def text(self) -> str:
        return self._body.decode()



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
            "baseCalculo": 0,
        }
    ]

    result = _monthly_expectation(event, rows)

    assert result is not None
    assert result["value"] == 0.31
    assert result["event_consensus"] is True
    assert result["provider"] == "BCB Focus"
    assert "08/26" in result["label"]



def test_monthly_focus_prefers_standard_30_day_sample() -> None:
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
            "Mediana": 0.40,
            "baseCalculo": 1,
        },
        {
            "Indicador": "IPCA",
            "Data": "2026-08-28",
            "DataReferencia": "08/2026",
            "Mediana": 0.31,
            "baseCalculo": 0,
        },
    ]

    result = _monthly_expectation(event, rows)

    assert result is not None
    assert result["value"] == 0.31



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
            "numeroRespondentes": 88,
            "baseCalculo": 0,
        },
        {
            "Indicador": "Selic",
            "Data": "2026-08-28",
            "Reuniao": "R7/2026",
            "Mediana": 14.0,
            "baseCalculo": 0,
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
            "Data": "2026-08-28",
            "DataReferencia": "2/2026",
            "Mediana": 0.6,
            "numeroRespondentes": 72,
            "baseCalculo": 0,
        }
    ]

    result = _quarterly_expectation(event, rows)

    assert result is not None
    assert result["value"] == 0.6
    assert result["label"] == "Focus BNP Q2 2026"



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



def test_annual_focus_proxy_is_removed_from_event_calendar() -> None:
    prepared = _prepare_calendar_rows(
        [
            {
                "date": "2026-09-11",
                "name": "IPCA",
                "kind": "inflation",
                "expectation": {
                    "event_consensus": False,
                    "label": "Focus 2026 IPCA (år)",
                    "value": 5.02,
                    "unit": "%",
                },
            }
        ]
    )

    assert "expectation" not in prepared[0]

    events = _annotate_market_consensus(prepared)
    event = events[0]
    assert "expectation" not in event
    assert event["market_consensus"]["ingested"] is False
    assert event["market_consensus"]["coverage"] == "BCB_FOCUS_EVENT_TEMPORARILY_UNAVAILABLE"



def test_pms_pmc_ibc_br_and_ipca15_do_not_get_annual_proxies() -> None:
    events = _annotate_market_consensus(
        [
            {"name": "Tjenesteaktivitet (PMS)", "kind": "services"},
            {"name": "Detaljhandel (PMC)", "kind": "retail"},
            {"name": "IBC-Br", "kind": "activity"},
            {"name": "IPCA-15", "kind": "inflation"},
        ]
    )

    for event in events:
        consensus = event["market_consensus"]
        assert consensus["available"] is True
        assert consensus["ingested"] is False
        assert consensus["coverage"] == "EXTERNAL_MARKET_CONSENSUS_NOT_INGESTED"
        assert "Markedskonsensus" in consensus["note"]



def test_focus_api_requests_are_reference_scoped_and_use_standard_sample() -> None:
    seen: list[str] = []

    async def fetcher(url: str, **_kwargs: object) -> _Response:
        seen.append(url)
        return _Response({"value": []})

    events = [
        {
            "date": "2026-09-01",
            "name": "BNP Q2",
            "kind": "gdp",
            "reference": "2026 Q2",
        },
        {
            "date": "2026-09-11",
            "name": "IPCA",
            "kind": "inflation",
            "reference": "aug. 2026",
        },
        {
            "date": "2026-09-16",
            "name": "Copom rentebeslutning",
            "kind": "copom",
        },
    ]

    asyncio.run(
        enrich_calendar_expectations(
            events,
            as_of_date="2026-08-29",
            fetcher=fetcher,
        )
    )

    assert len(seen) == 3
    queries = {urlparse(url).path.rsplit("/", 1)[-1]: parse_qs(urlparse(url).query) for url in seen}

    monthly_filter = unquote(queries["ExpectativaMercadoMensais"]["$filter"][0])
    quarterly_filter = unquote(queries["ExpectativasMercadoTrimestrais"]["$filter"][0])
    selic_filter = unquote(queries["ExpectativasMercadoSelic"]["$filter"][0])

    assert "baseCalculo eq 0" in monthly_filter
    assert "DataReferencia eq '08/2026'" in monthly_filter
    assert "baseCalculo eq 0" in quarterly_filter
    assert "DataReferencia eq '2/2026'" in quarterly_filter
    assert "baseCalculo eq 0" in selic_filter
    assert "Reuniao eq 'R6/2026'" in selic_filter
    assert "$select" in queries["ExpectativaMercadoMensais"]
    assert "$select" in queries["ExpectativasMercadoTrimestrais"]
    assert "$select" in queries["ExpectativasMercadoSelic"]

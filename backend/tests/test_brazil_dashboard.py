from __future__ import annotations

import sys
from pathlib import Path

WORKER_SRC = Path(__file__).resolve().parents[2] / "cloudflare" / "src"
if str(WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(WORKER_SRC))

from brazil_dashboard import (  # noqa: E402
    _load_focus,
    _load_sgs_series,
    _series_payload,
    calendar_events,
    parse_focus_rows,
)


class _Response:
    ok = True
    status = 200

    def __init__(self, payload: object) -> None:
        import json

        self._body = json.dumps(payload).encode()

    async def text(self) -> str:
        return self._body.decode()


def test_sgs_request_and_rows_are_capped_at_as_of_date() -> None:
    import asyncio
    from urllib.parse import parse_qs, urlparse

    seen: list[str] = []

    async def fetcher(url: str, **_kwargs: object) -> _Response:
        seen.append(url)
        return _Response([
            {"data": "28/08/2026", "valor": "14.5"},
            {"data": "30/08/2026", "valor": "99.0"},
        ])

    result = asyncio.run(_load_sgs_series("selic", as_of_date="2026-08-29", fetcher=fetcher))

    query = parse_qs(urlparse(seen[0]).query)
    assert query["dataFinal"] == ["29/08/2026"]
    assert result["date"] == "2026-08-28"
    assert result["value"] == 14.5


def test_focus_request_and_parser_are_capped_at_as_of_date() -> None:
    import asyncio
    from urllib.parse import parse_qs, unquote, urlparse

    seen: list[str] = []

    async def fetcher(url: str, **_kwargs: object) -> _Response:
        seen.append(url)
        return _Response({"value": [
            {"Indicador": "Selic", "Data": "2026-08-28", "DataReferencia": "2026", "Mediana": 12.5},
            {"Indicador": "Selic", "Data": "2026-08-30", "DataReferencia": "2026", "Mediana": 9.0},
        ]})

    result = asyncio.run(_load_focus("2026-08-29", fetcher=fetcher))

    query = parse_qs(urlparse(seen[0]).query)
    assert "Data le '2026-08-29'" in unquote(query["$filter"][0])
    assert result["values"]["selic"]["2026"]["median"] == 12.5


def test_parse_focus_rows_keeps_current_and_next_year() -> None:
    payload = {
        "value": [
            {
                "Indicador": "Selic",
                "Data": "2026-08-28",
                "DataReferencia": "2026",
                "Media": 12.6,
                "Mediana": 12.5,
                "Minimo": 11.0,
                "Maximo": 14.0,
                "numeroRespondentes": 90,
            },
            {
                "Indicador": "IPCA",
                "Data": "2026-08-28",
                "DataReferencia": "2027",
                "Media": 3.9,
                "Mediana": 3.8,
                "Minimo": 3.2,
                "Maximo": 4.5,
                "numeroRespondentes": 100,
            },
            {
                "Indicador": "Câmbio",
                "Data": "2026-08-28",
                "DataReferencia": "2027",
                "Media": 5.2,
                "Mediana": 5.1,
                "Minimo": 4.7,
                "Maximo": 5.8,
                "numeroRespondentes": 80,
            },
            {
                "Indicador": "Selic",
                "Data": "2026-08-28",
                "DataReferencia": "2028",
                "Mediana": 9.0,
            },
        ]
    }

    result = parse_focus_rows(payload, as_of_date="2026-08-29")

    assert result["selic"]["2026"]["median"] == 12.5
    assert result["ipca"]["2027"]["median"] == 3.8
    assert result["usd_brl"]["2027"]["median"] == 5.1
    assert "2028" not in result["selic"]


def test_calendar_uses_focus_as_directional_proxy_not_event_consensus() -> None:
    focus = {
        "selic": {"2026": {"median": 12.5, "survey_date": "2026-08-28"}},
        "ipca": {"2026": {"median": 4.1, "survey_date": "2026-08-28"}},
        "gdp": {"2026": {"median": 2.1, "survey_date": "2026-08-28"}},
    }

    events = calendar_events(as_of_date="2026-08-29", focus=focus)
    copom = next(item for item in events if item["date"] == "2026-09-16" and item["kind"] == "copom")
    ipca = next(item for item in events if item["date"] == "2026-09-11" and item["name"] == "IPCA")
    gdp = next(item for item in events if item["date"] == "2026-09-01" and item["kind"] == "gdp")

    assert copom["expectation"]["value"] == 12.5
    assert copom["expectation"]["event_consensus"] is False
    assert "årsslutt" in copom["expectation"]["label"]
    assert ipca["expectation"]["value"] == 4.1
    assert gdp["expectation"]["value"] == 2.1
    assert copom["importance"] == "Høy"
    assert "Bemobi" in copom["bemobi_impact"] or "multippel" in copom["bemobi_impact"]


def test_calendar_has_labelled_rolling_preview_after_seed_ends() -> None:
    events = calendar_events(as_of_date="2027-02-19", focus={})

    assert events
    assert all(item["date"] >= "2027-02-19" for item in events)
    estimated = [item for item in events if item.get("date_status") == "estimated"]
    assert estimated
    assert all(item["source_url"].startswith("https://") for item in estimated)


def test_index_series_is_presented_as_monthly_change() -> None:
    rows = [
        {"date": "2026-06-01", "value": 100},
        {"date": "2026-07-01", "value": 101},
    ]

    result = _series_payload("ibc_br", rows)

    assert result["value"] == 1.0
    assert result["unit"] == "% m/m"
    assert result["series"][-1]["value"] == 101.0

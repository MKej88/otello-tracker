from __future__ import annotations

import sys
from pathlib import Path

WORKER_SRC = Path(__file__).resolve().parents[2] / "cloudflare" / "src"
if str(WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(WORKER_SRC))

from brazil_dashboard import (  # noqa: E402
    _series_payload,
    calendar_events,
    parse_focus_rows,
)


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


def test_index_series_is_presented_as_monthly_change() -> None:
    rows = [
        {"date": "2026-06-01", "value": 100},
        {"date": "2026-07-01", "value": 101},
    ]

    result = _series_payload("ibc_br", rows)

    assert result["value"] == 1.0
    assert result["unit"] == "% m/m"
    assert result["series"][-1]["value"] == 101.0

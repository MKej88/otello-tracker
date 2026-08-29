from __future__ import annotations

import sys
from pathlib import Path

WORKER_SRC = Path(__file__).resolve().parents[2] / "cloudflare" / "src"
if str(WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(WORKER_SRC))

from brazil_calendar_expectations import (  # noqa: E402
    _monthly_expectation,
    _quarter_reference,
    _quarterly_expectation,
    _selic_expectation,
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
            "numeroRespondentes": 88,
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
            "Data": "2026-08-28",
            "DataReferencia": "2/2026",
            "Mediana": 0.6,
            "numeroRespondentes": 72,
        }
    ]

    result = _quarterly_expectation(event, rows)

    assert result is not None
    assert result["value"] == 0.6
    assert result["label"] == "Focus BNP Q2 2026"

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import pytest

WORKER_SRC = Path(__file__).resolve().parents[2] / "cloudflare" / "src"
if str(WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(WORKER_SRC))

from brazil_investor_insights import build_focus_trend, build_investor_summary  # noqa: E402


class _Response:
    ok = True
    status = 200

    def __init__(self, payload: object) -> None:
        import json

        self._body = json.dumps(payload).encode()

    async def text(self) -> str:
        return self._body.decode()


def _focus_payload(
    survey_date: str,
    *,
    current: tuple[float, float, float, float],
    next_year: tuple[float, float, float, float],
) -> dict:
    rows = []
    for year, values in (("2026", current), ("2027", next_year)):
        selic, ipca, gdp, usd_brl = values
        rows.extend(
            [
                {"Indicador": "Selic", "Data": survey_date, "DataReferencia": year, "Mediana": selic},
                {"Indicador": "IPCA", "Data": survey_date, "DataReferencia": year, "Mediana": ipca},
                {"Indicador": "PIB Total", "Data": survey_date, "DataReferencia": year, "Mediana": gdp},
                {"Indicador": "Câmbio", "Data": survey_date, "DataReferencia": year, "Mediana": usd_brl},
            ]
        )
    return {"value": rows}


def test_focus_trend_compares_current_and_next_year_7d_and_30d_back() -> None:
    async def fetcher(url: str, **_kwargs: object) -> _Response:
        query = parse_qs(urlparse(url).query)
        filter_text = unquote(query["$filter"][0])
        if "Data le '2026-08-29'" in filter_text:
            return _Response(
                _focus_payload(
                    "2026-08-28",
                    current=(13.25, 4.35, 1.85, 5.20),
                    next_year=(11.75, 4.10, 1.50, 5.25),
                )
            )
        if "Data le '2026-08-06'" in filter_text:
            return _Response(
                _focus_payload(
                    "2026-08-06",
                    current=(13.50, 4.50, 1.70, 5.25),
                    next_year=(12.00, 4.25, 1.40, 5.30),
                )
            )
        raise AssertionError(filter_text)

    current_focus = {
        "values": {
            "selic": {
                "2026": {"median": 13.00, "survey_date": "2026-09-05"},
                "2027": {"median": 11.50, "survey_date": "2026-09-05"},
            },
            "ipca": {
                "2026": {"median": 4.20, "survey_date": "2026-09-05"},
                "2027": {"median": 4.00, "survey_date": "2026-09-05"},
            },
            "gdp": {
                "2026": {"median": 1.90, "survey_date": "2026-09-05"},
                "2027": {"median": 1.60, "survey_date": "2026-09-05"},
            },
            "usd_brl": {
                "2026": {"median": 5.10, "survey_date": "2026-09-05"},
                "2027": {"median": 5.20, "survey_date": "2026-09-05"},
            },
        }
    }

    trend, status = asyncio.run(
        build_focus_trend(
            as_of_date="2026-09-05",
            current_focus=current_focus,
            fetcher=fetcher,
        )
    )

    assert status["ready"] is True
    assert trend["comparison_year"] == 2027
    assert trend["comparison_years"] == [2026, 2027]
    assert trend["comparisons"]["7d"]["points_by_year"]["2026"]["selic"]["change_bp"] == -25.0
    assert trend["comparisons"]["30d"]["points_by_year"]["2026"]["selic"]["change_bp"] == -50.0
    assert trend["comparisons"]["7d"]["points_by_year"]["2027"]["selic"]["change_bp"] == -25.0
    assert trend["comparisons"]["30d"]["points_by_year"]["2027"]["selic"]["change_bp"] == -50.0
    assert trend["comparisons"]["30d"]["points_by_year"]["2026"]["gdp"]["change"] == pytest.approx(0.2)
    assert trend["comparisons"]["30d"]["points_by_year"]["2027"]["gdp"]["change"] == pytest.approx(0.2)
    # Legacy next-year points remain available for other callers.
    assert trend["comparisons"]["30d"]["points"]["selic"]["year"] == 2027


def test_investor_summary_is_rule_based_and_separates_three_channels() -> None:
    result = {
        "as_of_date": "2026-09-05",
        "metrics": {
            "selic": {"value": 14.25},
            "brl_nok": {"change_1m_pct": 3.2},
            "ibc_br": {"value": 0.6},
            "ibc_services": {"value": 0.4},
        },
        "focus": {
            "values": {
                "selic": {
                    "2026": {"median": 13.0},
                    "2027": {"median": 11.5},
                }
            }
        },
    }
    trend = {
        "comparison_year": 2027,
        "comparisons": {
            "30d": {
                "points_by_year": {
                    "2027": {
                        "selic": {"change": -0.5},
                        "ipca": {"change": -0.1},
                    }
                }
            }
        },
    }

    summary = build_investor_summary(result, trend)

    assert summary["tone"] == "positive"
    assert summary["headline"] == "Makrobildet er i bedring"
    assert summary["drivers"]["valuation"]["tone"] == "positive"
    assert summary["drivers"]["operations"]["tone"] == "positive"
    assert summary["drivers"]["nav_fx"]["tone"] == "positive"
    assert summary["rate_path"]["expected_change_to_current_year_bp"] == -125.0
    assert summary["rate_path"]["expected_change_to_next_year_bp"] == -275.0
    assert summary["rate_path"]["expected_change_current_to_next_year_bp"] == -150.0
    assert "Ingen AI-score" in summary["method"]

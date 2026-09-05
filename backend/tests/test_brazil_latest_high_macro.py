from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

WORKER_SRC = Path(__file__).resolve().parents[2] / "cloudflare" / "src"
if str(WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(WORKER_SRC))

from brazil_dashboard_v2 import _resolve_latest_high_macro  # noqa: E402
from brazil_investing_consensus import _latest_high_importance_release  # noqa: E402


def test_latest_high_release_uses_actual_and_forecast_from_matching_event_page() -> None:
    events = [
        {
            "date": "2026-09-11",
            "name": "IPCA",
            "kind": "inflation",
            "importance": "Høy",
            "bemobi_impact": "Lavere inflasjon er normalt positivt for verdsettelsen.",
        }
    ]
    pages = {
        "ipca": (
            "https://www.investing.com/economic-calendar/brazil-consumer-price-index-%28cpi%29-mom-1165",
            [
                {
                    "date": "2026-09-11",
                    "time_utc": "12:00",
                    "actual": "0.24%",
                    "forecast": "0.31%",
                    "previous": "0.26%",
                }
            ],
        )
    }

    result = _latest_high_importance_release(events, pages, as_of_date="2026-09-11")

    assert result is not None
    assert result["date"] == "2026-09-11"
    assert result["actual"] == "0.24%"
    assert result["forecast"] == "0.31%"
    assert result["previous"] == "0.26%"
    assert result["surprise"] == -0.07
    assert result["importance"] == "Høy"


def test_latest_high_release_ignores_unreleased_rows() -> None:
    events = [
        {
            "date": "2026-09-11",
            "name": "IPCA",
            "kind": "inflation",
            "importance": "Høy",
            "bemobi_impact": "impact",
        }
    ]
    pages = {
        "ipca": (
            "https://example.com/ipca",
            [
                {
                    "date": "2026-09-11",
                    "time_utc": "12:00",
                    "actual": "",
                    "forecast": "0.31%",
                    "previous": "0.26%",
                }
            ],
        )
    }

    assert _latest_high_importance_release(events, pages, as_of_date="2026-09-11") is None


def test_latest_high_release_keeps_only_exact_high_importance() -> None:
    events = [
        {
            "date": "2026-09-10",
            "name": "Tjenester",
            "kind": "services",
            "importance": "Middels–høy",
            "bemobi_impact": "impact",
        }
    ]
    pages = {
        "services": (
            "https://example.com/services",
            [
                {
                    "date": "2026-09-10",
                    "time_utc": "12:00",
                    "actual": "0.5%",
                    "forecast": "0.3%",
                    "previous": "0.2%",
                }
            ],
        )
    }

    assert _latest_high_importance_release(events, pages, as_of_date="2026-09-10") is None


class _Repository:
    def __init__(self) -> None:
        self.value: str | None = None
        self.writes = 0

    async def first(self, _sql: str, _params: tuple[str, ...]):
        return None if self.value is None else {"value": self.value}

    async def run(self, _sql: str, params: tuple[str, ...]):
        self.value = params[1]
        self.writes += 1


def test_latest_high_macro_persists_until_newer_release_is_seen() -> None:
    repository = _Repository()
    first = {
        "date": "2026-09-04",
        "name": "IPCA",
        "kind": "inflation",
        "importance": "Høy",
        "actual": "0.20%",
    }
    newer = {
        "date": "2026-09-11",
        "name": "IPCA",
        "kind": "inflation",
        "importance": "Høy",
        "actual": "0.24%",
    }

    resolved = asyncio.run(
        _resolve_latest_high_macro(repository, first, as_of_date="2026-09-04")
    )
    assert resolved == first
    assert repository.writes == 1

    carried = asyncio.run(
        _resolve_latest_high_macro(repository, None, as_of_date="2026-09-10")
    )
    assert carried == first
    assert repository.writes == 1

    replaced = asyncio.run(
        _resolve_latest_high_macro(repository, newer, as_of_date="2026-09-11")
    )
    assert replaced == newer
    assert json.loads(repository.value or "{}")["date"] == "2026-09-11"
    assert repository.writes == 2


def test_brazil_frontend_shows_latest_release_in_compact_investor_view() -> None:
    frontend = (
        Path(__file__).resolve().parents[2] / "frontend" / "src" / "BrazilPage.tsx"
    ).read_text(encoding="utf-8")

    assert "SISTE VIKTIGE MAKROTALL" in frontend
    assert ">Faktisk<" in frontend
    assert ">Forventet<" in frontend
    assert ">Avvik<" in frontend
    assert "latest_high_importance_release.bemobi_impact" in frontend

    # Source-diagnostic text belongs on Datakvalitet, not in the primary investor view.
    assert "Forecast-feltet er tomt" not in frontend
    assert "hentingen feilet eller ble blokkert" not in frontend
    assert "ingen rad matcher den offisielle publiseringsdatoen" not in frontend

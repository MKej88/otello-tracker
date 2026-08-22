from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_full_workflow_uses_canonical_bemobi_runtime_import() -> None:
    entry = (ROOT / "cloudflare" / "src" / "entry.py").read_text(encoding="utf-8")

    assert "from bemobi_web_refresh_runtime import refresh_bemobi_web" in entry
    assert "from bemobi_web_refresh_v2 import refresh_bemobi_web" not in entry


def test_overview_preserves_last_good_forecast_on_isolated_failure() -> None:
    app = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")

    assert 'const loadForecast = async () =>' in app
    assert 'fetch("/api/buybacks/forecast")' in app
    assert 'setForecast((current) => current.ready' in app
    assert '{ ...current, status: "FETCH_STALE" }' in app
    assert '{ ready: false, status: "API_ERROR" }' in app
    assert 'forecast.status === "FETCH_STALE"' in app
    assert "PROGNOSE UTDATERT" in app
    assert "Viser sist gode prognose" in app

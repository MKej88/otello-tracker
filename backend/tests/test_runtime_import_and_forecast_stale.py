from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_full_workflow_uses_canonical_bemobi_runtime_import() -> None:
    entry = (ROOT / "cloudflare" / "src" / "entry.py").read_text(encoding="utf-8")

    assert "from bemobi_web_refresh_runtime import refresh_bemobi_web" in entry
    assert "from bemobi_web_refresh_v2 import refresh_bemobi_web" not in entry


def test_buyback_page_preserves_last_good_forecast_on_refresh_failure() -> None:
    page = (ROOT / "frontend" / "src" / "BuybackPage.tsx").read_text(encoding="utf-8")

    # Forecast is now shown on the buyback page as part of the dashboard.
    assert 'fetchPreloadedJson<Dashboard>("/api/buybacks/dashboard")' in page
    assert "const forecast = data?.forecast;" in page
    load = page.split("const load = () => {", 1)[1].split("load();", 1)[0]
    success, failure = load.split(".catch(() => {", 1)
    assert "setData(result)" in success
    assert "setFailed(false)" in success
    assert "setFailed(true)" in failure
    assert "setData(" not in failure
    assert "if (failed && data == null)" in page
    assert "Viser sist vellykket hentede data." in page
    assert "forecast?.ready" in page

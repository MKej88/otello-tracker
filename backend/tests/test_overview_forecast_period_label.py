from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OVERVIEW_PAGE = ROOT / "frontend" / "src" / "OverviewPage.tsx"
BUYBACK_PAGE = ROOT / "frontend" / "src" / "BuybackPage.tsx"


def test_overview_keeps_buyback_summary_compact_and_links_to_detail() -> None:
    overview = OVERVIEW_PAGE.read_text(encoding="utf-8")
    buyback = BUYBACK_PAGE.read_text(encoding="utf-8")

    assert 'timeZone: "Europe/Oslo"' in overview
    assert "forecastPeriodLabel" not in overview
    assert "forecast?.forecast_week" not in overview
    assert 'href="#tilbakekjop"' in overview
    assert "Se tilbakekjøpsprogram" in overview
    assert "Prognosenøyaktighet" in buyback

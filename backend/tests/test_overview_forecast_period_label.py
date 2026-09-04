from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OVERVIEW_PAGE = ROOT / "frontend" / "src" / "OverviewPage.tsx"


def test_overview_forecast_label_follows_actual_calendar_week() -> None:
    page = OVERVIEW_PAGE.read_text(encoding="utf-8")

    assert 'timeZone: "Europe/Oslo"' in page
    assert 'function forecastPeriodLabel(week?: { from?: string; to?: string })' in page
    assert 'if (forecastWeek === currentWeek) return "Denne uken";' in page
    assert 'if (forecastWeek === addDaysKey(currentWeek, 7)) return "Neste uke";' in page
    assert 'return forecastWeek > currentWeek ? "Kommende uke" : "Siste prognose";' in page
    assert '<span>{forecastPeriodLabel(forecast?.forecast_week)} – baseestimat</span>' in page
    assert '<span>Neste uke – baseestimat</span>' not in page

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUYBACK_PAGE = ROOT / "frontend" / "src" / "BuybackPage.tsx"


def test_forecast_period_label_follows_the_actual_calendar_week() -> None:
    page = BUYBACK_PAGE.read_text(encoding="utf-8")

    assert 'timeZone: "Europe/Oslo"' in page
    assert 'function forecastPeriodLabel(week?: ForecastWeek)' in page
    assert 'if (forecastWeek === currentWeek) return "Denne uken";' in page
    assert 'if (forecastWeek === addDaysKey(currentWeek, 7)) return "Neste uke";' in page
    assert 'return forecastWeek > currentWeek ? "Kommende uke" : "Siste prognose";' in page
    assert '<span className="label">{forecastPeriodLabel(forecast?.forecast_week)}</span>' in page
    assert '<span className="label">Neste uke</span>' not in page
    assert '"Neste handelsuke"' not in page
    assert '"Prognoseperiode ikke oppgitt"' in page

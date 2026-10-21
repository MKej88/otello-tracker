from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "frontend/src/BuybackPage.tsx"


def test_buyback_page_prioritizes_shareholder_value_creation() -> None:
    source = PAGE.read_text(encoding="utf-8")

    for label in (
        "Verdiskaping fra tilbakekjøp",
        "Netto NAV-effekt",
        "Kapital brukt",
        "Gjennomsnittlig kjøpskurs",
        "Aksjer kjøpt tilbake",
        "Effekt av færre aksjer",
        "Netto verdi skapt",
        "Programstatus",
        "Hvordan programmet faktisk gjennomføres",
    ):
        assert label in source

    for removed_label in (
        "Bemobi per 1 000 OTEC",
        "Slik leses effekten",
    ):
        assert removed_label not in source

    assert "share_count_nav_effect_per_share_nok" in source


def test_buyback_page_does_not_request_unused_bemobi_data() -> None:
    source = PAGE.read_text(encoding="utf-8")

    assert "/api/bemobi/dashboard" not in source
    assert "BemobiDashboard" not in source



def test_historical_forecast_price_warning_is_not_displayed_as_live_alert() -> None:
    """A Friday-locked price cap may be lower than today's amended mandate.

    Forecast price warnings remain model data, not live investor alerts.
    Other actionable alerts (data refresh errors and mandate expiry) stay.
    """
    source = PAGE.read_text(encoding="utf-8")

    assert "forecastWarning" not in source
    assert "warningLabel(estimate?.warning)" not in source
    assert "<strong>Kursbegrensning</strong>" not in source
    assert "{(completionWarning || failed) && (" in source
    assert "<strong>Ny oppdatering feilet.</strong>" in source
    assert "Makspris ved prognosetidspunkt" in source
    assert "Makspris" in source

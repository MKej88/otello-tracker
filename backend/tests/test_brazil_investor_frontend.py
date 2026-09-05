from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "frontend/src/BrazilPage.tsx"


def test_brazil_page_prioritizes_investor_impact_over_macro_terminal_detail() -> None:
    source = PAGE.read_text(encoding="utf-8")

    for text in (
        "Tre kanaler betyr mest for Otello",
        "RENTER",
        "BRL / NOK",
        "AKTIVITET",
        "HVA HAR ENDRET SEG?",
        "SISTE VIKTIGE MAKROTALL",
        "NESTE VIKTIGE HENDELSER",
        "MARKEDSFORVENTNINGER",
        "ALLE INDIKATORER",
        "FULL MAKROKALENDER",
        "KILDER OG METODE",
    ):
        assert text in source

    assert "summary?.headline" in source
    assert "summary?.tone" in source
    assert '"/api/brazil/dashboard"' in source
    assert '"/api/dashboard/economic"' in source
    assert "brlNavImpact10" in source
    assert "bemobiPerShare * 0.10" in source
    assert "Investing.com brukes bare som sekundær kilde" in source


def test_brazil_page_keeps_technical_source_errors_out_of_primary_view() -> None:
    source = PAGE.read_text(encoding="utf-8")

    assert "Investing.com-hentingen feilet" not in source
    assert "NO_FORECAST_PUBLISHED" not in source
    assert "SOURCE_ERROR" not in source
    assert "Ingen AI-score" not in source
    assert "AI-score" in source

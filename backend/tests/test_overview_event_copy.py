from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OVERVIEW = ROOT / "frontend" / "src" / "OverviewPage.tsx"


def test_overview_case_calendar_is_compact_and_investor_focused() -> None:
    page = OVERVIEW.read_text(encoding="utf-8")

    assert "NESTE VIKTIGE DATOER" in page
    assert "Hva bør følges nå?" in page
    assert 'event.importance.startsWith("Høy")' in page
    assert 'copom: "Rentebeslutning fra sentralbanken"' in page
    assert 'event.name.includes("15") ? "Foreløpig prisvekst" : "Prisvekst"' in page
    assert '"BCB – rentebeslutning"' not in page
    assert '"Brasil – IPCA"' not in page
    assert "basert på markedsverdier," not in page

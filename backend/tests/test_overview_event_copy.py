from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OVERVIEW = ROOT / "frontend" / "src" / "OverviewPage.tsx"


def test_overview_nav_copy_is_compact_and_case_calendar_is_investor_focused() -> None:
    page = OVERVIEW.read_text(encoding="utf-8")

    assert "Dagens beste estimat på verdien per Otello-aksje." in page
    assert "basert på markedsverdier," not in page
    assert "NESTE VIKTIGE DATOER" in page
    assert 'if (event.importance !== "Høy"' in page
    assert 'return "BCB – rentebeslutning";' in page
    assert '"Brasil – IPCA"' in page

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "frontend/src/OverviewPage.tsx"


def test_overview_is_a_compact_investor_cockpit() -> None:
    source = PAGE.read_text(encoding="utf-8")

    for text in (
        "HVA DRIVER NAV NÅ?",
        "De viktigste verdidriverne",
        "KAPITAL",
        "Cash og tilbakekjøp",
        "MARKED",
        "1 års median",
        "Se cash og kapitalallokering",
        "Se tilbakekjøpsprogram",
    ):
        assert text in source

    assert '"/api/news-events"' in source
    assert '"/api/brazil/dashboard"' in source
    assert '"/api/bemobi/dashboard"' not in source
    assert "MarketQuotePanelWithData" not in source
    assert "FreshnessCard" not in source
    assert "bemobi?.nav_effect_1m_per_share_nok" in source
    assert "brl?.nav_effect_1m_per_share_nok" in source
    assert "buybackNavEffect" in source
    assert 'href="#cash"' in source
    assert 'href="#tilbakekjop"' in source

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VIEWS = ROOT / "frontend" / "src" / "investorViews.ts"
NAV = ROOT / "frontend" / "src" / "InvestorNavigation.tsx"
STYLES = ROOT / "frontend" / "src" / "navigation-groups.css"
MAIN = ROOT / "frontend" / "src" / "main.tsx"
APP = ROOT / "frontend" / "src" / "InvestorApp.tsx"


def test_investor_navigation_is_grouped_without_changing_views() -> None:
    views = VIEWS.read_text(encoding="utf-8")
    nav = NAV.read_text(encoding="utf-8")
    styles = STYLES.read_text(encoding="utf-8")
    main = MAIN.read_text(encoding="utf-8")
    app = APP.read_text(encoding="utf-8")

    for label in ("Verdi", "Kapital", "Bemobi", "Informasjon"):
        assert f'label: "{label}"' in views

    assert 'items: ["Oversikt", "NAV", "NAV-sensitivitet", "Historikk"]' in views
    assert 'items: ["Tilbakekjøpsprogram", "Cash"]' in views
    assert 'items: ["Bemobi", "Konsensus", "Brasil"]' in views
    assert 'items: ["Nyheter", "Datakvalitet"]' in views
    assert "navigationGroups.flatMap" in views

    assert "navigationGroups.map" in nav
    assert 'className="navGroupLabel"' in nav
    assert 'className="navGroupItems"' in nav
    assert 'aria-label="Hovedmeny"' in nav

    assert ".navGroup + .navGroup" in styles
    assert ".navGroupLabel" in styles
    assert 'import "./navigation-groups.css"' in main
    assert 'import "./navigation-groups.css"' not in app

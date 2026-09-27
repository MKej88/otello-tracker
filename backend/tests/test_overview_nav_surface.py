from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STYLES = ROOT / "frontend" / "src" / "overview-page.css"
THEME = ROOT / "frontend" / "src" / "otello-theme.css"
PAGE = ROOT / "frontend" / "src" / "OverviewPage.tsx"
MAIN = ROOT / "frontend" / "src" / "main.tsx"


def test_overview_nav_uses_shared_card_surface_variants() -> None:
    styles = STYLES.read_text(encoding="utf-8")
    theme = THEME.read_text(encoding="utf-8")
    page = PAGE.read_text(encoding="utf-8")
    main = MAIN.read_text(encoding="utf-8")

    assert ".cardPrimary" in theme
    assert "background: var(--ot-surface-raised)" in theme
    assert ".cardSecondary" in theme
    assert "background: var(--ot-surface-muted)" in theme
    assert "border-color: var(--ot-border-soft)" in theme
    assert 'className="card cardPrimary overviewNavCard overviewNavCardV3"' in page
    assert 'className="cardSecondary"' in page
    assert "background:var(--ot-surface-inset)" not in styles
    assert 'import "./overview-surface-overrides.css"' not in main

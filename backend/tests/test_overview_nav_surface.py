from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STYLES = ROOT / "frontend" / "src" / "overview-page.css"
THEME = ROOT / "frontend" / "src" / "otello-theme.css"
MAIN = ROOT / "frontend" / "src" / "main.tsx"


def test_overview_nav_snapshot_uses_blue_tinted_inset_surface() -> None:
    styles = STYLES.read_text(encoding="utf-8")
    theme = THEME.read_text(encoding="utf-8")
    main = MAIN.read_text(encoding="utf-8")

    assert "--ot-surface-inset: #17283d" in theme
    assert "--ot-border-inset: rgba(79, 145, 212, 0.24)" in theme
    assert "background:var(--ot-surface-inset)" in styles
    assert "border:1px solid var(--ot-border-inset)" in styles
    assert 'import "./overview-surface-overrides.css"' not in main

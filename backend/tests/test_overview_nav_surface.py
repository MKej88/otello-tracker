from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STYLES = ROOT / "frontend" / "src" / "overview-surface-overrides.css"
MAIN = ROOT / "frontend" / "src" / "main.tsx"


def test_overview_nav_snapshot_uses_blue_tinted_inset_surface() -> None:
    styles = STYLES.read_text(encoding="utf-8")
    main = MAIN.read_text(encoding="utf-8")

    assert "--overview-inset-surface: #17283d" in styles
    assert "background: var(--overview-inset-surface)" in styles
    assert "border-color: rgba(79, 145, 212, 0.24)" in styles
    assert 'import "./overview-surface-overrides.css"' in main

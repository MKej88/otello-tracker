from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CSS = ROOT / "frontend" / "src" / "overview-page.css"
MAIN = ROOT / "frontend" / "src" / "main.tsx"


def test_overview_market_driver_headlines_keep_semantic_colors() -> None:
    css = CSS.read_text(encoding="utf-8")
    main = MAIN.read_text(encoding="utf-8")

    assert ".overviewDriverCard:nth-child(1):has(.overviewDriverEffect.positive)>strong" in css
    assert ".overviewDriverCard:nth-child(2):has(.overviewDriverEffect.positive)>strong" in css
    assert ".overviewDriverCard:nth-child(1):has(.overviewDriverEffect.negative)>strong" in css
    assert ".overviewDriverCard:nth-child(2):has(.overviewDriverEffect.negative)>strong" in css
    assert "color:var(--ot-positive)" in css
    assert "color:var(--ot-negative)" in css
    assert 'import "./overview-driver-colors.css"' not in main

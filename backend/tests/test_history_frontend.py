from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "frontend" / "src" / "EstimatedHistoryPage.tsx"
STYLES = ROOT / "frontend" / "src" / "history-context.css"
MAIN = ROOT / "frontend" / "src" / "main.tsx"


def test_history_adds_context_without_adding_another_value_series() -> None:
    page = PAGE.read_text(encoding="utf-8")
    styles = STYLES.read_text(encoding="utf-8")
    main = MAIN.read_text(encoding="utf-8")

    for token in (
        "historyPercentileBand",
        "historyMedianLine",
        "historyChartTooltip",
        "Avvik fra median",
        "Rabatten har bare vært større",
        "Live ·",
        "Siste historiske observasjon",
        "onPointerMove={handlePointerMove}",
    ):
        assert token in page

    for token in (
        ".historyPercentileBand",
        ".historyMedianLine",
        ".historyChartTooltip",
    ):
        assert token in styles

    assert '<span className="label">Gjennomsnitt</span>' not in page
    assert "hovered.nav_per_share" in page
    assert "estimatedNavLine" not in page
    assert 'import "./history-context.css"' in main

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend" / "src"


def read_frontend(name: str) -> str:
    return (FRONTEND / name).read_text(encoding="utf-8")


def test_theme_owns_shared_surface_semantic_and_chart_tokens() -> None:
    theme = read_frontend("otello-theme.css")

    for token in (
        "--ot-surface: #12161c",
        "--ot-surface-raised: #171c23",
        "--ot-surface-inset: #17283d",
        "--ot-surface-inset-nested: #142237",
        "--ot-border-inset: rgba(79, 145, 212, 0.24)",
        "--ot-positive: #36c99a",
        "--ot-positive-soft: rgba(54, 201, 154, 0.12)",
        "--ot-positive-border: rgba(54, 201, 154, 0.32)",
        "--ot-negative: #f06f7d",
        "--ot-negative-soft: rgba(240, 111, 125, 0.1)",
        "--ot-warning: #d2a851",
        "--ot-warning-soft: rgba(210, 168, 81, 0.1)",
        "--ot-chart-secondary: #55c9b5",
        "--ot-chart-reference: rgba(159, 193, 255, 0.9)",
        "--ot-chart-band: rgba(79, 139, 255, 0.08)",
        "--ot-chart-guide: rgba(255, 255, 255, 0.36)",
        "--ot-chart-point: #e6efff",
        "--ot-shadow-overlay: 0 12px 28px rgba(0, 0, 0, 0.25)",
    ):
        assert token in theme

    assert ":where(h1, h2, .card strong)" in theme
    assert "h1,\nh2,\n.card strong {" not in theme
    assert ".bemobiCleanHero" not in theme
    assert ".consensusHeroV2" not in theme
    assert ".buybackTable th" not in theme
    assert "!important" not in theme


def test_migrated_pages_consume_shared_tokens_directly() -> None:
    expected_tokens = {
        "cash-page.css": (
            "var(--ot-surface-inset)",
            "var(--ot-surface-raised)",
            "var(--ot-border-inset)",
        ),
        "buyback-page.css": (
            "var(--ot-positive-soft)",
            "var(--ot-warning-soft)",
            "var(--ot-surface-raised)",
        ),
        "bemobi-page.css": (
            "var(--ot-surface-inset)",
            "var(--ot-border-inset)",
            "var(--ot-positive)",
        ),
        "consensus-page.css": (
            "var(--ot-surface-raised)",
            "var(--ot-surface-inset)",
            "var(--ot-positive-soft)",
        ),
        "consensus-history.css": (
            "var(--ot-surface)",
            "var(--ot-surface-raised)",
            "var(--ot-accent-strong)",
        ),
    }

    hardcoded_colour = re.compile(r"#[0-9a-fA-F]{3,8}\b|rgba?\(")

    for filename, tokens in expected_tokens.items():
        source = read_frontend(filename)
        for token in tokens:
            assert token in source
        assert not hardcoded_colour.search(source), filename
        assert "!important" not in source

    assert "--bemobi-" not in read_frontend("bemobi-page.css")
    assert "--cash-inset-surface" not in read_frontend("cash-page.css")


def test_overview_reference_uses_same_shared_surface_contract() -> None:
    overview = read_frontend("overview-page.css")

    assert "background:var(--ot-surface-inset)" in overview
    assert "border:1px solid var(--ot-border-inset)" in overview
    assert "color:var(--ot-positive)" in overview
    assert "color:var(--ot-negative)" in overview


def test_cross_page_surface_override_layer_is_gone() -> None:
    main = read_frontend("main.tsx")

    assert 'import "./surface-hierarchy.css"' not in main
    assert not (FRONTEND / "surface-hierarchy.css").exists()

    for filename in (
        "cash-page.css",
        "buyback-page.css",
        "bemobi-page.css",
        "consensus-page.css",
    ):
        source = read_frontend(filename)
        assert "var(--ot-surface" in source
        assert "var(--ot-border" in source


def test_history_context_uses_shared_chart_contract() -> None:
    history = read_frontend("history-context.css")

    for token in (
        "var(--ot-chart-band)",
        "var(--ot-chart-reference)",
        "var(--ot-chart-guide)",
        "var(--ot-chart-point)",
        "var(--ot-chart-secondary)",
        "var(--ot-chart-band-border)",
        "var(--ot-chart-band-legend)",
        "var(--ot-shadow-overlay)",
    ):
        assert token in history


def test_theme_load_order_is_explicit_and_old_override_files_are_gone() -> None:
    main = read_frontend("main.tsx")
    app = read_frontend("InvestorApp.tsx")

    base_index = main.index('import "./styles.css"')
    theme_index = main.index('import "./otello-theme.css"')
    history_index = main.index('import "./history-context.css"')
    assert base_index < theme_index < history_index
    assert 'import "./otello-theme.css"' not in app

    for removed_name in (
        "cash-surface-overrides.css",
        "overview-driver-colors.css",
        "overview-surface-overrides.css",
        "surface-hierarchy.css",
    ):
        assert removed_name not in main
        assert not (FRONTEND / removed_name).exists()

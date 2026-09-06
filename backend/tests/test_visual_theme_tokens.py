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


def test_all_non_theme_stylesheets_consume_shared_palette() -> None:
    hardcoded_colour = re.compile(r"#[0-9a-fA-F]{3,8}\b|rgba?\(")
    css_files = sorted(FRONTEND.glob("*.css"))

    assert css_files
    assert (FRONTEND / "otello-theme.css") in css_files

    for path in css_files:
        if path.name == "otello-theme.css":
            continue
        source = path.read_text(encoding="utf-8")
        assert not hardcoded_colour.search(source), path.name
        assert "!important" not in source, path.name


def test_migrated_pages_consume_shared_tokens_directly() -> None:
    expected_tokens = {
        "cash-page.css": ("var(--ot-surface-inset)", "var(--ot-surface-raised)", "var(--ot-border-inset)"),
        "buyback-page.css": ("var(--ot-positive-soft)", "var(--ot-warning-soft)", "var(--ot-surface-raised)"),
        "bemobi-page.css": ("var(--ot-surface-raised)", "var(--ot-surface-muted)", "var(--ot-border-soft)", "var(--ot-positive)"),
        "consensus-page.css": ("var(--ot-surface-raised)", "var(--ot-surface-inset)", "var(--ot-positive-soft)"),
        "consensus-history.css": ("var(--ot-surface)", "var(--ot-surface-raised)", "var(--ot-accent-strong)"),
        "brazil-page.css": ("var(--ot-surface-raised)", "var(--ot-warning-soft)", "var(--ot-chart-secondary)"),
        "data-quality.css": ("var(--ot-surface-raised)", "var(--ot-positive-soft)", "var(--ot-warning-soft)"),
        "nav-sensitivity.css": ("var(--ot-surface-raised)", "var(--ot-accent-soft)", "var(--ot-negative-soft)"),
        "market-quote-panel.css": ("var(--ot-surface)", "var(--ot-track)", "var(--ot-positive)"),
        "economic-nav.css": ("var(--ot-surface)", "var(--ot-surface-raised)", "var(--ot-positive-border)"),
        "styles.css": ("var(--ot-border-soft)", "var(--ot-warning-soft)", "var(--ot-chart-secondary)"),
        "investor-v2.css": ("var(--ot-border-soft)", "var(--ot-positive)", "var(--ot-chart-secondary)"),
        "overview-page.css": ("var(--ot-surface-inset)", "var(--ot-positive)", "var(--ot-accent-soft)", "var(--ot-control-soft)"),
        "news-events.css": ("var(--ot-surface)", "var(--ot-warning)", "var(--ot-positive-soft)"),
        "navigation-groups.css": ("var(--ot-border-soft)", "var(--ot-text-muted)"),
        "bemobi-source-status.css": ("var(--ot-positive)", "var(--ot-warning-border)", "var(--ot-negative)"),
        "nav-waterfall.css": ("var(--ot-surface)", "var(--ot-positive)", "var(--ot-warning-soft)"),
        "report-status.css": ("var(--ot-surface-raised)", "var(--ot-positive-soft)", "var(--ot-warning-soft)"),
        "runtime-status.css": ("var(--ot-surface-raised)", "var(--ot-negative-soft)", "var(--ot-warning-soft)"),
        "history-page.css": ("var(--ot-surface-inset)", "var(--ot-chart-reference)", "var(--ot-warning-soft)"),
    }

    for filename, tokens in expected_tokens.items():
        source = read_frontend(filename)
        for token in tokens:
            assert token in source

    bemobi = read_frontend("bemobi-page.css")
    assert "--bemobi-" not in bemobi
    assert "var(--ot-surface-inset)" not in bemobi
    assert "var(--ot-border-inset)" not in bemobi
    assert "--cash-inset-surface" not in read_frontend("cash-page.css")

    for filename in ("brazil-page.css", "news-events.css"):
        source = read_frontend(filename)
        for legacy_token in ("var(--muted)", "var(--border)", "var(--accent", "var(--text)", "var(--line)"):
            assert legacy_token not in source


def test_overview_reference_uses_same_shared_surface_contract() -> None:
    overview = read_frontend("overview-page.css")

    assert "background:var(--ot-surface-inset)" in overview
    assert "border:1px solid var(--ot-border-inset)" in overview
    assert "background:var(--ot-accent-soft)" in overview
    assert "background:var(--ot-control-soft)" in overview
    assert "color:var(--ot-positive)" in overview
    assert "color:var(--ot-negative)" in overview


def test_cross_page_surface_override_layer_is_gone() -> None:
    main = read_frontend("main.tsx")

    assert 'import "./surface-hierarchy.css"' not in main
    assert not (FRONTEND / "surface-hierarchy.css").exists()


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


def test_global_stylesheet_order_is_owned_by_entrypoint() -> None:
    main = read_frontend("main.tsx")
    app = read_frontend("InvestorApp.tsx")

    base_index = main.index('import "./styles.css"')
    theme_index = main.index('import "./otello-theme.css"')
    investor_index = main.index('import "./investor-v2.css"')
    navigation_index = main.index('import "./navigation-groups.css"')
    history_index = main.index('import "./history-context.css"')
    assert base_index < theme_index < investor_index < navigation_index < history_index

    assert 'import "./investor-v2.css"' not in app
    assert 'import "./navigation-groups.css"' not in app
    assert 'import "./otello-theme.css"' not in app
    assert 'import "./prelive.css"' not in main
    assert not (FRONTEND / "prelive.css").exists()

    for removed_name in (
        "cash-surface-overrides.css",
        "overview-driver-colors.css",
        "overview-surface-overrides.css",
        "surface-hierarchy.css",
        "prelive.css",
    ):
        assert removed_name not in main
        assert not (FRONTEND / removed_name).exists()

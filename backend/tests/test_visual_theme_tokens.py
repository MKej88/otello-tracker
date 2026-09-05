from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend" / "src"


def read_frontend(name: str) -> str:
    return (FRONTEND / name).read_text(encoding="utf-8")


def test_theme_owns_shared_inset_and_chart_tokens() -> None:
    theme = read_frontend("otello-theme.css")

    for token in (
        "--ot-surface-inset: #17283d",
        "--ot-surface-inset-nested: #142237",
        "--ot-surface-hero: linear-gradient(180deg, #17283d, #121c2b)",
        "--ot-border-inset: rgba(79, 145, 212, 0.24)",
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


def test_cash_and_overview_use_shared_surface_contract() -> None:
    cash = read_frontend("cash-page.css")
    overview = read_frontend("overview-page.css")

    assert "--cash-inset-surface: var(--ot-surface-inset)" in cash
    assert "background: var(--ot-surface-inset-nested)" in cash
    assert "var(--ot-border-inset)" in cash

    assert "background:var(--ot-surface-inset)" in overview
    assert "border:1px solid var(--ot-border-inset)" in overview
    assert "color:var(--ot-positive)" in overview
    assert "color:var(--ot-negative)" in overview


def test_investor_pages_share_one_surface_hierarchy() -> None:
    theme = read_frontend("otello-theme.css")

    for selector in (
        ".bemobiCleanHero",
        ".consensusHeroV2",
        ".bemobiCleanSection",
        ".accuracyGrid > div",
        ".bemobiDriverGrid > div",
        ".consensusWaitingPreview",
        ".buybackTable th",
        ".bemobiQuarterTable th",
        ".consensusTable th",
    ):
        assert selector in theme

    assert "background: var(--ot-surface-hero);" in theme
    assert "background: var(--ot-surface);" in theme
    assert "background: var(--ot-surface-inset);" in theme
    assert "background: var(--ot-surface-inset-nested);" in theme
    assert "border-color: var(--ot-border-inset);" in theme
    assert "!important" not in theme


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


def test_theme_load_order_is_explicit_and_override_files_are_gone() -> None:
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
    ):
        assert removed_name not in main
        assert not (FRONTEND / removed_name).exists()

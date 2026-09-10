from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "frontend" / "src" / "CashPage.tsx"
APP = ROOT / "frontend" / "src" / "InvestorApp.tsx"
THEME = ROOT / "frontend" / "src" / "otello-theme.css"


def test_cash_page_shows_how_estimated_cash_is_derived() -> None:
    source = PAGE.read_text(encoding="utf-8")

    for token in (
        "OTELLO CASH-MODELL",
        "Estimert cash i dag",
        "Rapportert kontantbeholdning",
        "cashBridge?.movements",
        "movement.label",
        "Endring siden siste rapport",
        "Siste rapporterte kontantbeholdning",
        "cashBridge?.report_date",
        "cashBridge?.cash_per_share_nok",
    ):
        assert token in source

    assert "signedMoneyM(movement.amount_mnok)" in source
    assert "movementTone(movement.amount_mnok)" in source
    assert "movementTone(cashBridge?.change_since_report_mnok)" in source
    assert "Kontantkvalitet</span>" not in source
    assert "Kalibrering</span>" not in source


def test_cash_bridge_preserves_positive_and_negative_colors_inside_cards() -> None:
    theme = THEME.read_text(encoding="utf-8")

    assert ":where(h1, h2, .card strong)" in theme
    assert ".positive," in theme
    assert "color: var(--ot-positive);" in theme
    assert ".negative," in theme
    assert "color: var(--ot-negative);" in theme


def test_cash_navigation_reuses_requests_started_before_module_load() -> None:
    page_source = PAGE.read_text(encoding="utf-8")
    app_source = APP.read_text(encoding="utf-8")
    cash_preload = app_source.split('if (view === "Cash")', maxsplit=1)[1].split(
        "}", maxsplit=1
    )[0]

    for url in (
        "/api/dashboard/summary",
        "/api/bemobi/dashboard",
        "/api/dashboard/economic",
        "/api/buybacks/dashboard",
    ):
        assert f'preloadJson("{url}")' in cash_preload

    assert "/api/nav/daily-cash" not in cash_preload
    assert 'import { fetchPreloadedJson } from "./navigationDataPreload"' in page_source
    assert "const request = initial ? fetchPreloadedJson : fetchJson" in page_source
    assert "void loadCore(true)" in page_source
    assert "void loadBuyback(true)" in page_source

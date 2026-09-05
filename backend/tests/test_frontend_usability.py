from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend" / "src"


def read_frontend(name: str) -> str:
    return (FRONTEND / name).read_text(encoding="utf-8")


def test_investor_navigation_is_split_into_a_small_component() -> None:
    app = read_frontend("InvestorApp.tsx")
    navigation = read_frontend("InvestorNavigation.tsx")

    assert 'import InvestorNavigation from "./InvestorNavigation"' in app
    assert '<nav aria-label="Hovedmeny">' in navigation
    assert 'aria-current={item === activeView ? "page" : undefined}' in navigation


def test_navigation_only_preloads_after_intentional_hover() -> None:
    navigation = read_frontend("InvestorNavigation.tsx")

    assert "HOVER_PRELOAD_DELAY_MS = 120" in navigation
    assert "onMouseEnter={() => scheduleHoverPreload(item)}" in navigation
    assert "onMouseLeave={cancelHoverPreload}" in navigation
    assert "onFocus={() => onPreload(item)}" in navigation


def test_views_support_deep_links_and_update_the_browser_title() -> None:
    app = read_frontend("InvestorApp.tsx")
    views = read_frontend("investorViews.ts")

    assert "window.location.hash = viewSlugs[view]" in app
    assert "viewFromHash(window.location.hash)" in app
    assert "document.title = `${viewTitles[activeView]} | Otello`" in app
    for slug in ("oversikt", "nav", "historikk", "tilbakekjop", "datakvalitet"):
        assert f'"{slug}"' in views


def test_skip_link_targets_focusable_main_content() -> None:
    app = read_frontend("InvestorApp.tsx")

    assert 'href="#main-content"' in app
    assert "event.preventDefault()" in app
    assert 'document.getElementById("main-content")?.focus()' in app
    assert 'id="main-content" tabIndex={-1}' in app


def test_shared_formatting_and_resource_messages_are_used() -> None:
    overview = read_frontend("OverviewPage.tsx")
    history = read_frontend("EstimatedHistoryPage.tsx")
    quality = read_frontend("DataQualityPage.tsx")

    assert 'from "./uiFormat"' in overview
    assert 'from "./uiFormat"' in history
    assert 'from "./uiFormat"' in quality
    assert 'from "./ResourceNotice"' in history
    assert 'kind="error"' in history


def test_data_quality_shows_safe_preflight_warning_messages() -> None:
    quality = read_frontend("DataQualityPage.tsx")

    assert "warnings?: Array<{ code: string; message: string }>" in quality
    assert "nightly?.preflight?.warnings ?? []" in quality
    assert ".map((warning) => warning.message)" in quality


def test_data_quality_explains_partial_status_and_bemobi_fallback() -> None:
    quality = read_frontend("DataQualityPage.tsx")

    assert "«Delvis» betyr at kjøringen ble fullført" in quality
    assert "stopper" in quality
    assert "ikke oppdateringen når antall blokkeringer er 0" in quality
    assert "kilden ble ikke fullt oppdatert" in quality
    assert "siste gode data er beholdt" in quality


def test_history_chart_has_a_text_summary() -> None:
    history = read_frontend("EstimatedHistoryPage.tsx")

    assert 'role="img"' in history
    assert 'className="chartSummary"' in history
    assert "Siste rabatt er" in history
    assert "siste OTEC-kurs er" in history


def test_cash_movement_explanations_are_permanently_visible_in_calculation_column() -> None:
    nav_page = read_frontend("NavPageV2.tsx")
    styles = read_frontend("investor-v2.css")

    assert "<span>Beregning</span>" in nav_page
    assert "displayFormula(item)" in nav_page
    assert 'item.formula.replace("Estimert NAV", "NAV")' in nav_page
    assert 'label: "Bemobi-utbetalinger"' in nav_page
    assert "Rest etter identifiserte kontantbevegelser" in nav_page
    assert "white-space:pre-line" in styles
    assert "accordion" not in nav_page.lower()
    assert 'title={displayFormula(item)}' not in nav_page


def test_news_page_prioritizes_investor_relevance_over_ingestion_diagnostics() -> None:
    news = read_frontend("NewsEventsPage.tsx")

    for label in (
        "Siste relevante hendelser for Otello og Bemobi",
        "NESTE VIKTIGE DATO",
        "VIKTIGST NÅ",
        "Det som kan flytte caset",
        "Viktige",
        "Vis flere",
        "Automatisk oversatt fra portugisisk · basert på RSS-metadata",
    ):
        assert label in news

    assert "MEDIAINNHENTING" not in news
    assert "mediaRefreshMetrics" not in news
    assert "feeds</span>" not in news
    assert 'item.category === "JCP" ? "JCP"' in news

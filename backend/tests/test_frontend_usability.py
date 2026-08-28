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


def test_history_chart_has_a_text_summary() -> None:
    history = read_frontend("EstimatedHistoryPage.tsx")

    assert 'role="img"' in history
    assert 'className="chartSummary"' in history
    assert "Siste rabatt er" in history
    assert "siste OTEC-kurs er" in history

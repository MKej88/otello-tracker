from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
FRONTEND_SRC = ROOT / "frontend" / "src"
FRONTEND_INDEX = ROOT / "frontend" / "index.html"


def _top_level_import_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.lstrip(".").split(".", 1)[0])
    return roots


def test_bootstrap_hot_snapshot_does_not_eagerly_import_heavy_calculators() -> None:
    imports = _top_level_import_roots(CLOUDFLARE_SRC / "dashboard_hot_snapshot.py")
    assert imports.isdisjoint(
        {
            "buyback_service",
            "dashboard_service",
            "economic_nav_investor",
            "quote_details",
        }
    )


def test_fastapi_app_does_not_eagerly_import_route_business_modules() -> None:
    imports = _top_level_import_roots(CLOUDFLARE_SRC / "app.py")
    assert imports.isdisjoint(
        {
            "bemobi_consensus_investor",
            "bemobi_dashboard",
            "bemobi_source_status",
            "buyback_dashboard",
            "buyback_service",
            "dashboard_service",
            "discount_history",
            "economic_nav_investor",
            "fx_backtest",
            "nav_waterfall_attribution_enrich",
            "nav_waterfall_settlement",
            "quote_details",
            "report_status",
            "runtime_status",
        }
    )


def test_frontend_keeps_bounded_last_good_bootstrap_for_repeat_first_paint() -> None:
    source = (FRONTEND_SRC / "dashboardBootstrapFetch.ts").read_text(encoding="utf-8")
    assert 'CLIENT_CACHE_KEY = "otello.dashboard.bootstrap.v1"' in source
    assert "CLIENT_CACHE_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000" in source
    assert "window.localStorage.getItem" in source
    assert "window.localStorage.setItem" in source
    assert 'syntheticResponse(cachedComponent, "CLIENT_CACHE")' in source
    assert "bootstrapPromise = fetchBootstrap(originalFetch)" in source


def test_cached_first_screen_is_only_parsed_once_before_react_render() -> None:
    source = (FRONTEND_SRC / "dashboardBootstrapFetch.ts").read_text(encoding="utf-8")

    cache_check = source.index(
        "if (storedBootstrap !== undefined) return storedBootstrap;"
    )
    storage_read = source.index("window.localStorage.getItem(CLIENT_CACHE_KEY)")

    assert cache_check < storage_read
    assert "storedBootstrap = stored as StoredBootstrap" in source
    assert "storedBootstrap = stored;" in source


def test_client_cache_never_replaces_background_network_revalidation() -> None:
    source = (FRONTEND_SRC / "dashboardBootstrapFetch.ts").read_text(encoding="utf-8")
    cache_return = source.index('return syntheticResponse(cachedComponent, "CLIENT_CACHE")')
    network_start = source.index("bootstrapPromise = fetchBootstrap(originalFetch)")
    assert network_start < cache_return


def test_network_revalidation_reaches_the_first_screen_without_waiting_for_polling() -> None:
    bootstrap = (FRONTEND_SRC / "dashboardBootstrapFetch.ts").read_text(
        encoding="utf-8"
    )
    polling = (FRONTEND_SRC / "usePollingResource.ts").read_text(encoding="utf-8")

    assert "servedFromClientCache.add(component)" in bootstrap
    assert "bootstrapPromise.then(publishRevalidatedBootstrap)" in bootstrap
    assert "subscribeDashboardRevalidation<T>(url" in polling
    assert "unsubscribeRevalidation?.()" in polling


def test_repeat_visit_renders_cached_first_screen_before_react_effects() -> None:
    bootstrap = (FRONTEND_SRC / "dashboardBootstrapFetch.ts").read_text(
        encoding="utf-8"
    )
    polling = (FRONTEND_SRC / "usePollingResource.ts").read_text(encoding="utf-8")
    overview = (FRONTEND_SRC / "OverviewPage.tsx").read_text(encoding="utf-8")

    assert "getCachedDashboardComponentForUrl<T>(url)" in polling
    assert "useState<T | null>(() =>" in polling
    assert "usePreloadedInitial ? getCachedDashboardComponentForUrl" in polling
    assert overview.count("    true,\n  );") == 4
    assert '"/api/dashboard/discount-history?days=365&max_points=72"' in overview
    assert "bootstrapPromise = fetchBootstrap(originalFetch)" in bootstrap


def test_repeat_visit_renders_cached_market_quotes_on_first_render() -> None:
    quotes = (FRONTEND_SRC / "MarketQuotePanel.tsx").read_text(encoding="utf-8")

    assert "usePollingResource<MarketQuotePayload>(" in quotes
    assert '    "/api/market/quotes",' in quotes
    assert "    true," in quotes
    assert 'fetch("/api/market/quotes")' not in quotes


def test_html_preloads_first_screen_data_before_javascript() -> None:
    source = FRONTEND_INDEX.read_text(encoding="utf-8")
    preload_start = source.index('rel="preload"')
    script_start = source.index('type="module"')

    assert preload_start < script_start
    assert 'href="/api/dashboard/bootstrap"' in source
    assert 'as="fetch"' in source
    assert 'crossorigin="anonymous"' in source
    assert 'fetchpriority="high"' in source


def test_navigation_starts_history_data_before_route_is_mounted() -> None:
    app_source = (FRONTEND_SRC / "InvestorApp.tsx").read_text(encoding="utf-8")
    nav_source = (FRONTEND_SRC / "NavPageV2.tsx").read_text(encoding="utf-8")
    history_source = (FRONTEND_SRC / "EstimatedHistoryPage.tsx").read_text(
        encoding="utf-8"
    )

    assert "preloadJson(discountHistoryUrl(investorPeriods()[0]))" in app_source
    assert "preloadJson(discountHistoryUrl(investorPeriods()[4]))" in app_source
    assert "preload(initialView)" in app_source
    assert "preload(view)" in app_source
    assert "fetchPreloadedJson<Payload>(discountHistoryUrl(period))" in nav_source
    assert "fetchPreloadedJson<Payload>(discountHistoryUrl(period))" in history_source


def test_navigation_starts_buyback_data_in_parallel_with_route_code() -> None:
    app_source = (FRONTEND_SRC / "InvestorApp.tsx").read_text(encoding="utf-8")
    buyback_source = (FRONTEND_SRC / "BuybackPage.tsx").read_text(encoding="utf-8")

    buyback_preload = app_source.index('if (view === "Tilbakekjøpsprogram")')
    buyback_route = app_source.index('window.location.hash = viewSlugs[view]')

    assert buyback_preload < buyback_route
    assert 'preloadJson("/api/buybacks/dashboard")' in app_source
    assert (
        'fetchPreloadedJson<Dashboard>("/api/buybacks/dashboard")'
        in buyback_source
    )


def test_data_quality_starts_all_visible_data_while_route_code_loads() -> None:
    app_source = (FRONTEND_SRC / "InvestorApp.tsx").read_text(encoding="utf-8")
    source_status = (FRONTEND_SRC / "BemobiSourceStatusPanel.tsx").read_text(
        encoding="utf-8"
    )

    quality_preload = app_source.index('if (view === "Datakvalitet")')
    quality_route = app_source.index('window.location.hash = viewSlugs[view]')

    assert quality_preload < quality_route
    assert 'preloadJson("/api/dashboard/runtime-status")' in app_source
    assert 'preloadJson("/api/dashboard/report-status")' in app_source
    assert 'preloadJson("/api/bemobi/source-status")' in app_source
    assert "usePollingResource<SourceStatus>(" in source_status
    assert '    "/api/bemobi/source-status",' in source_status
    assert "    true," in source_status
    assert 'fetch("/api/bemobi/source-status")' not in source_status


def test_navigation_shares_bemobi_request_while_route_code_loads() -> None:
    app_source = (FRONTEND_SRC / "InvestorApp.tsx").read_text(encoding="utf-8")
    page_source = (FRONTEND_SRC / "BemobiPage.tsx").read_text(encoding="utf-8")
    base_source = (FRONTEND_SRC / "BemobiPageBase.tsx").read_text(encoding="utf-8")

    bemobi_preload = app_source.index('if (view === "Bemobi")')
    bemobi_route = app_source.index('window.location.hash = viewSlugs[view]')

    assert bemobi_preload < bemobi_route
    assert 'preloadJson("/api/bemobi/dashboard")' in app_source
    assert (
        'fetchPreloadedJson<BemobiDashboard>("/api/bemobi/dashboard")'
        in base_source
    )
    assert "<BemobiPageBase />" in page_source


def test_bemobi_clean_page_has_one_dashboard_polling_owner() -> None:
    page_source = (FRONTEND_SRC / "BemobiPage.tsx").read_text(encoding="utf-8")
    base_source = (FRONTEND_SRC / "BemobiPageBase.tsx").read_text(
        encoding="utf-8"
    )

    # BemobiPage is now only a thin wrapper. The base view owns the single refresh
    # timer for /api/bemobi/dashboard, so no duplicate tax/source polling is added.
    assert 'fetch("/api/bemobi/dashboard")' not in page_source
    assert "<BemobiPageBase />" in page_source
    assert "BemobiTaxPanel" not in page_source
    assert "window.setInterval(load, AUTO_REFRESH_MS)" in base_source
    assert base_source.count('fetch("/api/bemobi/dashboard")') == 1


def test_navigation_starts_consensus_data_in_parallel_with_route_code() -> None:
    app_source = (FRONTEND_SRC / "InvestorApp.tsx").read_text(encoding="utf-8")
    page_source = (FRONTEND_SRC / "ConsensusPage.tsx").read_text(encoding="utf-8")

    consensus_preload = app_source.index('if (view === "Konsensus")')
    consensus_route = app_source.index('window.location.hash = viewSlugs[view]')

    assert consensus_preload < consensus_route
    assert 'preloadJson("/api/bemobi/consensus")' in app_source
    assert (
        'fetchPreloadedJson<ConsensusPayload>("/api/bemobi/consensus")'
        in page_source
    )


def test_recent_navigation_data_is_reused_when_a_view_is_reopened() -> None:
    source = (FRONTEND_SRC / "navigationDataPreload.ts").read_text(encoding="utf-8")

    assert "const NAVIGATION_CACHE_MS = 30_000" in source
    assert "cached.expiresAt > Date.now()" in source
    assert "resolvedJson.set(url" in source
    assert "if (cached) resolvedJson.delete(url)" in source

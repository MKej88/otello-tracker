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


def test_client_cache_never_replaces_background_network_revalidation() -> None:
    source = (FRONTEND_SRC / "dashboardBootstrapFetch.ts").read_text(encoding="utf-8")
    cache_return = source.index('return syntheticResponse(cachedComponent, "CLIENT_CACHE")')
    network_start = source.index("bootstrapPromise = fetchBootstrap(originalFetch)")
    assert network_start < cache_return


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

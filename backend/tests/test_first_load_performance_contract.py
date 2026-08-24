from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
FRONTEND_SRC = ROOT / "frontend" / "src"


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

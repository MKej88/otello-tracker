from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
FRONTEND_SRC = ROOT / "frontend" / "src"


def test_nightly_history_completion_materializes_nav_period_cache() -> None:
    source = (CLOUDFLARE_SRC / "estimated_nav_history_materialization.py").read_text(
        encoding="utf-8"
    )
    cache_source = (CLOUDFLARE_SRC / "materialized_discount_history.py").read_text(
        encoding="utf-8"
    )

    assert "materialize_discount_periods" in source
    assert '"period_cache": period_cache' in source
    assert '"status": "deferred"' in source
    assert '"reason": "history_scan_continues"' in source
    assert 'PERIOD_KEYS = ("1m", "3m", "6m", "ytd", "1y", "3y")' in cache_source
    assert 'PERIOD_CACHE_KEY_PREFIX = "materialized_discount_period"' in cache_source
    assert "NAV_PERIODS_V2" in cache_source
    assert "estimated_period_not_current" in cache_source
    assert "payload = await discount_history(" in cache_source
    assert "return await _enrich_life360_period(repository, payload)" in cache_source


def test_nav_page_preloads_all_materialized_periods_with_one_bundle_request() -> None:
    app_source = (FRONTEND_SRC / "InvestorApp.tsx").read_text(encoding="utf-8")
    preload_source = (FRONTEND_SRC / "navigationDataPreload.ts").read_text(
        encoding="utf-8"
    )
    api_source = (CLOUDFLARE_SRC / "app.py").read_text(encoding="utf-8")

    assert "preloadNavPeriodBundle(Object.fromEntries(" in app_source
    assert "investorPeriods().map((period) => [period.key, discountHistoryUrl(period)])" in app_source
    assert 'NAV_PERIOD_BUNDLE_URL = "/api/dashboard/nav-periods"' in preload_source
    assert "const payload = { estimated };" in preload_source
    assert '@app.get("/api/dashboard/nav-periods")' in api_source
    assert "materialized_nav_period_bundle" in api_source


def test_discount_history_presets_use_materialized_cache_with_enriched_live_fallback() -> None:
    api_source = (CLOUDFLARE_SRC / "app.py").read_text(encoding="utf-8")
    cache_source = (CLOUDFLARE_SRC / "materialized_discount_history.py").read_text(
        encoding="utf-8"
    )

    assert "from materialized_discount_history import materialized_discount_history" in api_source
    assert "latest_history_date = await _latest_history_date(repository)" in cache_source
    assert 'entry.get("source_date") == latest_history_date' in cache_source
    assert "return dict(entry[\"payload\"])" in cache_source
    assert "payload = await discount_history(" in cache_source
    assert "return await _enrich_life360_period(repository, payload)" in cache_source
    assert "apply_historical_life360_change_split" in cache_source

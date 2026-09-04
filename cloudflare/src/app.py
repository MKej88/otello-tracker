from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query, Request

from dashboard_hot_snapshot import dashboard_bootstrap_payload, dashboard_hot_component
from performance_repository import PerformanceD1Repository, PerformanceD1WriteRepository

API_VERSION = "0.13.2"

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}

CACHE_POLICIES = {
    "/api/health": ("no-store", "no-store"),
    "/api/dashboard/bootstrap": ("public, max-age=15", "public, max-age=300, stale-while-revalidate=1800"),
    "/api/dashboard/summary": ("public, max-age=15", "public, max-age=300, stale-while-revalidate=1800"),
    "/api/dashboard/report-status": ("public, max-age=30", "public, max-age=120, stale-while-revalidate=300"),
    "/api/dashboard/runtime-status": ("public, max-age=15", "public, max-age=30, stale-while-revalidate=60"),
    "/api/dashboard/economic": ("public, max-age=15", "public, max-age=300, stale-while-revalidate=1800"),
    "/api/dashboard/waterfall": ("public, max-age=15", "public, max-age=60, stale-while-revalidate=120"),
    "/api/dashboard/fx-backtest": ("public, max-age=1800", "public, max-age=21600, stale-while-revalidate=43200"),
    "/api/dashboard/history": ("public, max-age=300", "public, max-age=1800, stale-while-revalidate=3600"),
    "/api/dashboard/discount-history": ("public, max-age=300", "public, max-age=1800, stale-while-revalidate=3600"),
    "/api/dashboard/nav-periods": ("public, max-age=300", "public, max-age=1800, stale-while-revalidate=3600"),
    "/api/buybacks/forecast": ("public, max-age=300", "public, max-age=900, stale-while-revalidate=1800"),
    "/api/buybacks/dashboard": ("public, max-age=60", "public, max-age=300, stale-while-revalidate=600"),
    "/api/bemobi/dashboard": ("public, max-age=60", "public, max-age=300, stale-while-revalidate=600"),
    "/api/bemobi/consensus": ("public, max-age=300", "public, max-age=1800, stale-while-revalidate=3600"),
    "/api/bemobi/source-status": ("public, max-age=30", "public, max-age=120, stale-while-revalidate=300"),
    "/api/brazil/dashboard": ("public, max-age=300", "public, max-age=1800, stale-while-revalidate=3600"),
    "/api/news-events": ("public, max-age=60", "public, max-age=300, stale-while-revalidate=600"),
    "/api/market/quotes": ("public, max-age=30", "public, max-age=300, stale-while-revalidate=1800"),
}

app = FastAPI(
    title="Otello NAV-oversikt",
    version=API_VERSION,
    description="Cloudflare Worker API for Otello NAV-oversikt",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.middleware("http")
async def add_response_hardening(request: Request, call_next):
    response = await call_next(request)
    for header, value in SECURITY_HEADERS.items():
        response.headers[header] = value
    browser_policy, edge_policy = CACHE_POLICIES.get(request.url.path, ("no-store", "no-store"))
    response.headers["Cache-Control"] = browser_policy
    response.headers["Cloudflare-CDN-Cache-Control"] = edge_policy
    return response


def _repository(request: Request) -> PerformanceD1Repository:
    env = request.scope.get("env")
    database = getattr(env, "DB", None) if env is not None else None
    if database is None:
        raise HTTPException(status_code=503, detail="D1 binding unavailable")
    return PerformanceD1Repository(database)


def _write_repository(request: Request) -> PerformanceD1WriteRepository:
    env = request.scope.get("env")
    database = getattr(env, "DB", None) if env is not None else None
    if database is None:
        raise HTTPException(status_code=503, detail="D1 binding unavailable")
    return PerformanceD1WriteRepository(database)


@app.get("/api/health")
async def health(request: Request) -> dict[str, str]:
    repository = _repository(request)
    try:
        row = await repository.first("SELECT 1 AS ok")
    except Exception as exc:
        raise HTTPException(status_code=503, detail="D1 unavailable") from exc
    if row is None or int(row.get("ok", 0)) != 1:
        raise HTTPException(status_code=503, detail="D1 unavailable")
    env = request.scope.get("env")
    revision = str(getattr(env, "DEPLOYMENT_REVISION", "") or "local")
    return {
        "status": "ok",
        "service": "otello-api",
        "environment": "cloudflare",
        "version": API_VERSION,
        "revision": revision,
    }


@app.get("/api/dashboard/bootstrap")
async def get_dashboard_bootstrap(request: Request) -> dict:
    return await dashboard_bootstrap_payload(_repository(request))


@app.get("/api/dashboard/summary")
async def get_dashboard_summary(request: Request) -> dict:
    repository = _repository(request)
    cached = await dashboard_hot_component(repository, "summary")
    if cached is not None:
        return cached
    from dashboard_service import dashboard_summary, enrich_dashboard_summary

    summary = await dashboard_summary(repository)
    return await enrich_dashboard_summary(summary, repository)


@app.get("/api/dashboard/report-status")
async def get_report_status(request: Request) -> dict:
    from report_status import report_status_summary

    return await report_status_summary(_repository(request))


@app.get("/api/dashboard/runtime-status")
async def get_runtime_status(request: Request) -> dict:
    from runtime_status import runtime_status_summary

    return await runtime_status_summary(_repository(request))


@app.get("/api/dashboard/economic")
async def get_economic_nav(request: Request) -> dict:
    repository = _repository(request)
    cached = await dashboard_hot_component(repository, "economic")
    if cached is not None:
        return cached
    from economic_nav_investor import economic_nav_summary

    return await economic_nav_summary(repository)


@app.get("/api/dashboard/waterfall")
async def get_nav_waterfall(request: Request) -> dict:
    from nav_waterfall_attribution_enrich import enrich_nav_waterfall
    from nav_waterfall_settlement import nav_waterfall_summary

    repository = _repository(request)
    settled = await nav_waterfall_summary(repository)
    return await enrich_nav_waterfall(repository, settled)


@app.get("/api/dashboard/fx-backtest")
async def get_fx_backtest(request: Request) -> dict:
    from fx_backtest import fx_backtest_summary

    return await fx_backtest_summary(_repository(request))


@app.get("/api/dashboard/history")
async def get_dashboard_history(
    request: Request,
    days: int = Query(default=365, ge=7, le=3650),
    max_points: int = Query(default=400, ge=50, le=1000),
) -> dict:
    from dashboard_service import dashboard_history

    repository = _repository(request)
    return await dashboard_history(repository, days=days, max_points=max_points)


@app.get("/api/dashboard/discount-history")
async def get_discount_history(
    request: Request,
    days: int = Query(default=365, ge=30, le=3650),
    max_points: int = Query(default=600, ge=50, le=1000),
    year_to_date: bool = Query(default=False),
) -> dict:
    from materialized_discount_history import materialized_discount_history

    return await materialized_discount_history(
        _repository(request),
        days=days,
        max_points=max_points,
        year_to_date=year_to_date,
    )


@app.get("/api/dashboard/nav-periods")
async def get_nav_periods(request: Request) -> dict:
    from materialized_discount_history import materialized_nav_period_bundle

    return await materialized_nav_period_bundle(_repository(request))


@app.get("/api/market/quotes")
async def get_market_quotes(request: Request) -> dict:
    repository = _repository(request)
    cached = await dashboard_hot_component(repository, "quotes")
    if cached is not None:
        return cached
    from quote_details import market_quote_details

    return await market_quote_details(repository)


@app.get("/api/buybacks/forecast")
async def get_buyback_forecast(
    request: Request,
    as_of_date: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> dict:
    repository = _repository(request)
    try:
        if as_of_date is None:
            cached = await dashboard_hot_component(repository, "forecast")
            if cached is not None:
                return cached
        from buyback_service import buyback_forecast

        return await buyback_forecast(repository, as_of_date=as_of_date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid as_of_date") from exc


@app.get("/api/buybacks/dashboard")
async def get_buyback_dashboard(
    request: Request,
    as_of_date: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> dict:
    from buyback_dashboard import buyback_dashboard

    repository = _repository(request)
    try:
        return await buyback_dashboard(repository, as_of_date=as_of_date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid as_of_date") from exc


@app.get("/api/bemobi/dashboard")
async def get_bemobi_dashboard(request: Request) -> dict:
    from bemobi_dashboard import bemobi_dashboard

    return await bemobi_dashboard(_repository(request))


@app.get("/api/bemobi/consensus")
async def get_bemobi_consensus(request: Request) -> dict:
    from bemobi_consensus_investor import bemobi_consensus

    return await bemobi_consensus(_repository(request))


@app.get("/api/bemobi/source-status")
async def get_bemobi_source_status(request: Request) -> dict:
    from bemobi_source_status import bemobi_source_status

    return await bemobi_source_status(_repository(request))


@app.get("/api/brazil/dashboard")
async def get_brazil_dashboard(
    request: Request,
    as_of_date: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> dict:
    from brazil_dashboard_v2 import brazil_dashboard

    try:
        # Focus resilience persists last-good annual and event-specific expectations.
        return await brazil_dashboard(_write_repository(request), as_of_date=as_of_date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid as_of_date") from exc


@app.get("/api/news-events")
async def get_news_events(
    request: Request,
    as_of_date: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    limit: int = Query(default=60, ge=1, le=100),
) -> dict:
    from news_events import news_and_events

    try:
        return await news_and_events(
            _repository(request),
            as_of_date=as_of_date,
            news_limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid as_of_date") from exc

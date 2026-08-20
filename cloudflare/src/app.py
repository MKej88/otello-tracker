from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query, Request

from bemobi_consensus_investor import bemobi_consensus
from bemobi_dashboard import bemobi_dashboard
from buyback_dashboard import buyback_dashboard
from buyback_service import buyback_forecast
from dashboard_service import dashboard_history, dashboard_summary, enrich_dashboard_summary
from economic_nav_investor import economic_nav_summary
from fx_backtest import fx_backtest_summary
from nav_waterfall_settlement import nav_waterfall_summary
from performance_repository import PerformanceD1Repository
from quote_details import market_quote_details
from report_status import report_status_summary
from shareholders import shareholders_dashboard

API_VERSION = "0.12.0"

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}

CACHE_POLICIES = {
    "/api/health": ("no-store", "no-store"),
    "/api/dashboard/summary": ("public, max-age=15", "public, max-age=60, stale-while-revalidate=120"),
    "/api/dashboard/report-status": ("public, max-age=30", "public, max-age=120, stale-while-revalidate=300"),
    "/api/dashboard/economic": ("public, max-age=15", "public, max-age=60, stale-while-revalidate=120"),
    "/api/dashboard/waterfall": ("public, max-age=15", "public, max-age=60, stale-while-revalidate=120"),
    "/api/dashboard/fx-backtest": ("public, max-age=1800", "public, max-age=21600, stale-while-revalidate=43200"),
    "/api/dashboard/history": ("public, max-age=300", "public, max-age=1800, stale-while-revalidate=3600"),
    "/api/buybacks/forecast": ("public, max-age=300", "public, max-age=900, stale-while-revalidate=1800"),
    "/api/buybacks/dashboard": ("public, max-age=60", "public, max-age=300, stale-while-revalidate=600"),
    "/api/bemobi/dashboard": ("public, max-age=60", "public, max-age=300, stale-while-revalidate=600"),
    "/api/bemobi/consensus": ("public, max-age=300", "public, max-age=1800, stale-while-revalidate=3600"),
    "/api/market/quotes": ("public, max-age=30", "public, max-age=60, stale-while-revalidate=120"),
    "/api/shareholders/dashboard": ("public, max-age=300", "public, max-age=1800, stale-while-revalidate=3600"),
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


@app.get("/api/health")
async def health(request: Request) -> dict[str, str]:
    repository = _repository(request)
    try:
        row = await repository.first("SELECT 1 AS ok")
    except Exception as exc:
        raise HTTPException(status_code=503, detail="D1 unavailable") from exc
    if row is None or int(row.get("ok", 0)) != 1:
        raise HTTPException(status_code=503, detail="D1 unavailable")
    return {"status": "ok", "service": "otello-api", "environment": "cloudflare", "version": API_VERSION}


@app.get("/api/dashboard/summary")
async def get_dashboard_summary(request: Request) -> dict:
    repository = _repository(request)
    summary = await dashboard_summary(repository)
    return await enrich_dashboard_summary(summary, repository)


@app.get("/api/dashboard/report-status")
async def get_report_status(request: Request) -> dict:
    return await report_status_summary(_repository(request))


@app.get("/api/dashboard/economic")
async def get_economic_nav(request: Request) -> dict:
    return await economic_nav_summary(_repository(request))


@app.get("/api/dashboard/waterfall")
async def get_nav_waterfall(request: Request) -> dict:
    return await nav_waterfall_summary(_repository(request))


@app.get("/api/dashboard/fx-backtest")
async def get_fx_backtest(request: Request) -> dict:
    return await fx_backtest_summary(_repository(request))


@app.get("/api/dashboard/history")
async def get_dashboard_history(
    request: Request,
    days: int = Query(default=365, ge=7, le=3650),
    max_points: int = Query(default=400, ge=50, le=1000),
) -> dict:
    repository = _repository(request)
    return await dashboard_history(repository, days=days, max_points=max_points)


@app.get("/api/market/quotes")
async def get_market_quotes(request: Request) -> dict:
    return await market_quote_details(_repository(request))


@app.get("/api/buybacks/forecast")
async def get_buyback_forecast(
    request: Request,
    as_of_date: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> dict:
    repository = _repository(request)
    try:
        return await buyback_forecast(repository, as_of_date=as_of_date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid as_of_date") from exc


@app.get("/api/buybacks/dashboard")
async def get_buyback_dashboard(
    request: Request,
    as_of_date: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> dict:
    repository = _repository(request)
    try:
        return await buyback_dashboard(repository, as_of_date=as_of_date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid as_of_date") from exc


@app.get("/api/bemobi/dashboard")
async def get_bemobi_dashboard(request: Request) -> dict:
    return await bemobi_dashboard(_repository(request))


@app.get("/api/bemobi/consensus")
async def get_bemobi_consensus(request: Request) -> dict:
    return await bemobi_consensus(_repository(request))


@app.get("/api/shareholders/dashboard")
async def get_shareholders_dashboard(request: Request) -> dict:
    return await shareholders_dashboard(_repository(request))

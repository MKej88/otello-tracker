from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query, Request

from buyback_service import buyback_forecast
from dashboard_service import dashboard_history, dashboard_summary, enrich_dashboard_summary
from economic_nav import economic_nav_summary
from fx_backtest import fx_backtest_summary
from performance_repository import PerformanceD1Repository

API_VERSION = "0.11.2"

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}

CACHE_POLICIES = {
    "/api/health": "no-store",
    "/api/dashboard/summary": "public, max-age=30",
    "/api/dashboard/economic": "public, max-age=30",
    "/api/dashboard/fx-backtest": "public, max-age=3600",
    "/api/dashboard/history": "public, max-age=900",
    "/api/buybacks/forecast": "public, max-age=900",
}

app = FastAPI(
    title="Otello NAV Dashboard",
    version=API_VERSION,
    description="Cloudflare Worker API for Otello NAV Dashboard",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.middleware("http")
async def add_response_hardening(request: Request, call_next):
    response = await call_next(request)
    for header, value in SECURITY_HEADERS.items():
        response.headers[header] = value
    response.headers["Cache-Control"] = CACHE_POLICIES.get(request.url.path, "no-store")
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
    return {
        "status": "ok",
        "service": "otello-api",
        "environment": "cloudflare",
        "version": API_VERSION,
    }


@app.get("/api/dashboard/summary")
async def get_dashboard_summary(request: Request) -> dict:
    repository = _repository(request)
    summary = await dashboard_summary(repository)
    return await enrich_dashboard_summary(summary, repository)


@app.get("/api/dashboard/economic")
async def get_economic_nav(request: Request) -> dict:
    return await economic_nav_summary(_repository(request))


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

from contextlib import asynccontextmanager

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from app.buybacks import buyback_status
from app.dashboard import dashboard_history as get_dashboard_history
from app.dashboard import dashboard_summary as get_dashboard_summary
from app.db.migration_runner import database_status, init_database
from app.history import history_status, seed_curated_history
from app.marketdata import market_data_status
from app.nav import daily_cash_status, daily_nav_status, full_nav_status, other_net_assets_status
from app.nav.core_nav import core_nav_status
from app.settings import settings


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_database(settings.database_path)
    seed_curated_history(settings.database_path)
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.8.0",
    description="Backend for Otello NAV Dashboard",
    lifespan=lifespan,
)

origins = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "otello-api",
        "environment": settings.app_env,
        "version": "0.8.0",
    }


@app.get("/api/system/database")
def system_database() -> dict:
    return database_status(settings.database_path)


@app.get("/api/system/history")
def system_history() -> dict:
    return history_status(settings.database_path)


@app.get("/api/system/market-data")
def system_market_data() -> dict:
    return market_data_status(settings.database_path)


@app.get("/api/buybacks/status")
def system_buybacks() -> dict:
    return buyback_status(settings.database_path)


@app.get("/api/nav/core-anchors")
def nav_core_anchors() -> dict:
    return core_nav_status(settings.database_path)


@app.get("/api/nav/daily-cash")
def nav_daily_cash() -> dict:
    return daily_cash_status(settings.database_path)


@app.get("/api/nav/daily")
def nav_daily() -> dict:
    return daily_nav_status(settings.database_path)


@app.get("/api/nav/other-net-assets")
def nav_other_net_assets() -> dict:
    return other_net_assets_status(settings.database_path)


@app.get("/api/nav/full")
def nav_full() -> dict:
    return full_nav_status(settings.database_path)


@app.get("/api/dashboard/summary")
def dashboard_summary() -> dict:
    init_database(settings.database_path)
    return get_dashboard_summary(settings.database_path)


@app.get("/api/dashboard/history")
def dashboard_history(
    days: int = Query(default=365, ge=7, le=3650),
    max_points: int = Query(default=400, ge=50, le=1000),
) -> dict:
    init_database(settings.database_path)
    return get_dashboard_history(
        settings.database_path,
        days=days,
        max_points=max_points,
    )

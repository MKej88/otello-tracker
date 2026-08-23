from contextlib import asynccontextmanager

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from app.bemobi import bemobi_cvm_news_status, list_bemobi_news
from app.bemobi.consensus_investor import bemobi_consensus
from app.bemobi.dashboard import bemobi_dashboard
from app.bemobi.source_status import bemobi_source_status
from app.buybacks import (
    buyback_forecast,
    buyback_status,
    market_activity_status,
    seed_otec_activity_history,
)
from app.buybacks.dashboard import buyback_dashboard
from app.dashboard import dashboard_history as get_dashboard_history
from app.dashboard import dashboard_summary as get_dashboard_summary
from app.dashboard_freshness import enrich_dashboard_summary
from app.db.migration_runner import database_status, init_database
from app.discount_history import discount_history as get_discount_history
from app.economic_nav_investor import economic_nav_summary
from app.fx_backtest import fx_backtest_summary
from app.history import history_status, seed_curated_history_if_needed
from app.marketdata import market_data_status
from app.marketdata.quote_details import market_quote_details
from app.nav import daily_cash_status, daily_nav_status, full_nav_status, other_net_assets_status
from app.nav.core_nav import core_nav_status
from app.nav_waterfall_attribution import nav_waterfall_summary
from app.settings import settings


API_VERSION = "0.12.0"


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_database(settings.database_path)
    seed_curated_history_if_needed(settings.database_path)
    seed_otec_activity_history(settings.database_path)
    yield


app = FastAPI(
    title=settings.app_name,
    version=API_VERSION,
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
        "version": API_VERSION,
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


@app.get("/api/system/market-activity")
def system_market_activity() -> dict:
    return market_activity_status(settings.database_path)


@app.get("/api/market/quotes")
def market_quotes() -> dict:
    return market_quote_details(settings.database_path)


@app.get("/api/buybacks/status")
def system_buybacks() -> dict:
    return buyback_status(settings.database_path)


@app.get("/api/buybacks/forecast")
def system_buyback_forecast(
    as_of_date: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> dict:
    return buyback_forecast(settings.database_path, as_of_date=as_of_date)


@app.get("/api/buybacks/dashboard")
def system_buyback_dashboard(
    as_of_date: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> dict:
    return buyback_dashboard(settings.database_path, as_of_date=as_of_date)


@app.get("/api/bemobi/dashboard")
def bemobi_investor_dashboard() -> dict:
    return bemobi_dashboard(settings.database_path)


@app.get("/api/bemobi/consensus")
def bemobi_consensus_dashboard() -> dict:
    return bemobi_consensus(settings.database_path)


@app.get("/api/bemobi/source-status")
def bemobi_source_status_dashboard() -> dict:
    return bemobi_source_status(settings.database_path)


@app.get("/api/bemobi/news")
def bemobi_news(
    limit: int = Query(default=50, ge=1, le=200),
    category: str | None = Query(default=None),
    include_superseded: bool = Query(default=False),
) -> dict:
    return list_bemobi_news(
        settings.database_path,
        limit=limit,
        category=category,
        include_superseded=include_superseded,
    )


@app.get("/api/bemobi/news/status")
def bemobi_news_status() -> dict:
    return bemobi_cvm_news_status(settings.database_path)


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
    summary = get_dashboard_summary(settings.database_path)
    return enrich_dashboard_summary(summary, settings.database_path)


@app.get("/api/dashboard/economic")
def dashboard_economic_nav() -> dict:
    return economic_nav_summary(settings.database_path)


@app.get("/api/dashboard/waterfall")
def dashboard_nav_waterfall() -> dict:
    return nav_waterfall_summary(settings.database_path)


@app.get("/api/dashboard/fx-backtest")
def dashboard_fx_backtest() -> dict:
    return fx_backtest_summary(settings.database_path)


@app.get("/api/dashboard/history")
def dashboard_history(
    days: int = Query(default=365, ge=7, le=3650),
    max_points: int = Query(default=400, ge=50, le=1000),
) -> dict:
    return get_dashboard_history(
        settings.database_path,
        days=days,
        max_points=max_points,
    )


@app.get("/api/dashboard/discount-history")
def dashboard_discount_history(
    days: int = Query(default=365, ge=30, le=3650),
    max_points: int = Query(default=600, ge=50, le=1000),
) -> dict:
    return get_discount_history(
        settings.database_path,
        days=days,
        max_points=max_points,
    )

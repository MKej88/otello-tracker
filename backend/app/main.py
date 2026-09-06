import math
from contextlib import asynccontextmanager
from datetime import date
from typing import Any

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from app.api_models import HealthResponse
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
from app.economic_nav_investor import economic_nav_summary
from app.fx_backtest import fx_backtest_summary
from app.fx_dashboard import fx_dashboard
from app.history import history_status, seed_curated_history_if_needed
from app.marketdata import market_data_status
from app.marketdata.quote_details import market_quote_details
from app.materialized_discount_history import (
    materialized_discount_history as get_discount_history,
)
from app.materialized_discount_history import materialized_nav_period_bundle
from app.nav import (
    daily_cash_status,
    daily_nav_status,
    full_nav_status,
    other_net_assets_status,
)
from app.nav.core_nav import core_nav_status
from app.nav_waterfall_attribution_enrich import enrich_nav_waterfall
from app.nav_waterfall_settlement import nav_waterfall_summary
from app.news_events import news_events_dashboard
from app.settings import settings


API_VERSION = "0.12.1"


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _discount_pct(otec_price: float | None, nav_per_share: Any) -> float | None:
    nav = _finite_number(nav_per_share)
    if otec_price is None or otec_price <= 0 or nav is None or nav <= 0:
        return None
    return (1 - otec_price / nav) * 100


def _canonical_otec_quote() -> dict[str, Any]:
    """Returner samme OTEC-quote som /api/market/quotes bruker."""
    payload = market_quote_details(settings.database_path)
    quote = dict((payload.get("symbols") or {}).get("OTEC") or {})
    price = _finite_number(quote.get("last"))
    if not quote.get("ready") or price is None or price <= 0:
        return {}
    quote["last"] = price
    return quote


def _sync_summary_with_otec_quote(
    summary: dict[str, Any], quote: dict[str, Any]
) -> dict[str, Any]:
    """Synkroniser alle nåverdier i dashboard-summary mot kanonisk OTEC-quote."""
    price = _finite_number(quote.get("last"))
    if price is None or price <= 0:
        return summary

    result = dict(summary)
    old_discount = _finite_number(result.get("nav_discount_pct"))
    current_discount = _discount_pct(price, result.get("nav_per_share"))

    result.update(
        {
            "otec_price": price,
            "otec_price_updated_at": quote.get("last_updated_at"),
            "otec_price_trading_date": quote.get("trading_date"),
            "otec_price_type": quote.get("last_price_type"),
            "otec_price_source": quote.get("source"),
        }
    )
    if current_discount is not None:
        result["nav_discount_pct"] = current_discount

    insights = dict(result.get("nav_discount_insights") or {})
    if insights:
        previous_insight_discount = _finite_number(insights.get("discount_pct"))
        insights["share_price"] = price
        insights["discount_pct"] = current_discount
        nav = _finite_number(insights.get("nav_per_share"))
        insights["upside_to_nav_pct"] = (
            (nav / price - 1) * 100
            if nav is not None and nav > 0 and price > 0
            else None
        )
        month_change = _finite_number(insights.get("month_change_pp"))
        if (
            current_discount is not None
            and previous_insight_discount is not None
            and month_change is not None
        ):
            insights["month_change_pp"] = (
                month_change + current_discount - previous_insight_discount
            )
        range_1y = dict(insights.get("range_1y") or {})
        low = _finite_number(range_1y.get("low"))
        high = _finite_number(range_1y.get("high"))
        if current_discount is not None and low is not None and high is not None:
            range_1y["position_pct"] = (
                50.0 if high == low else (current_discount - low) / (high - low) * 100
            )
        insights["range_1y"] = range_1y
        result["nav_discount_insights"] = insights

    changes = dict(result.get("changes") or {})
    quote_daily_pct = _finite_number((quote.get("changes") or {}).get("daily_pct"))
    if quote_daily_pct is not None:
        changes["otec_pct"] = quote_daily_pct
    discount_change = _finite_number(changes.get("discount_pp"))
    if (
        current_discount is not None
        and old_discount is not None
        and discount_change is not None
    ):
        changes["discount_pp"] = discount_change + current_discount - old_discount
    if changes:
        result["changes"] = changes

    return result


def _sync_economic_with_otec_quote(
    payload: dict[str, Any], quote: dict[str, Any]
) -> dict[str, Any]:
    """Beregn live rabatt fra samme OTEC-quote som resten av applikasjonen."""
    price = _finite_number(quote.get("last"))
    if price is None or price <= 0:
        return payload

    result = dict(payload)
    result.update(
        {
            "otec_price": price,
            "otec_price_updated_at": quote.get("last_updated_at"),
            "otec_price_trading_date": quote.get("trading_date"),
            "otec_price_type": quote.get("last_price_type"),
            "otec_price_source": quote.get("source"),
            "discount_pct": _discount_pct(price, result.get("nav_per_share")),
            "conservative_discount_pct": _discount_pct(
                price, result.get("conservative_nav_per_share")
            ),
        }
    )
    return result


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

origins = [
    origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service="otello-api",
        environment=settings.app_env,
        version=API_VERSION,
    )


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
    as_of_date: date | None = Query(default=None),
) -> dict:
    return buyback_forecast(
        settings.database_path,
        as_of_date=as_of_date.isoformat() if as_of_date else None,
    )


@app.get("/api/buybacks/dashboard")
def system_buyback_dashboard(
    as_of_date: date | None = Query(default=None),
) -> dict:
    return buyback_dashboard(
        settings.database_path,
        as_of_date=as_of_date.isoformat() if as_of_date else None,
    )


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


@app.get("/api/news-events")
async def news_events(
    as_of_date: date | None = Query(default=None),
    limit: int = Query(default=60, ge=1, le=100),
) -> dict:
    return await news_events_dashboard(
        settings.database_path,
        as_of_date=as_of_date.isoformat() if as_of_date else None,
        news_limit=limit,
    )


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
    summary = enrich_dashboard_summary(summary, settings.database_path)
    return _sync_summary_with_otec_quote(summary, _canonical_otec_quote())


@app.get("/api/dashboard/economic")
def dashboard_economic_nav() -> dict:
    payload = economic_nav_summary(settings.database_path)
    return _sync_economic_with_otec_quote(payload, _canonical_otec_quote())


@app.get("/api/dashboard/waterfall")
def dashboard_nav_waterfall() -> dict:
    settled = nav_waterfall_summary(settings.database_path)
    return enrich_nav_waterfall(settled, database_path=settings.database_path)


@app.get("/api/dashboard/fx-backtest")
def dashboard_fx_backtest() -> dict:
    return fx_backtest_summary(settings.database_path)


@app.get("/api/fx/dashboard")
def dashboard_fx() -> dict:
    return fx_dashboard(settings.database_path)


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
    year_to_date: bool = Query(default=False),
) -> dict:
    return get_discount_history(
        settings.database_path,
        days=days,
        max_points=max_points,
        year_to_date=year_to_date,
    )


@app.get("/api/dashboard/nav-periods")
def dashboard_nav_periods() -> dict:
    return materialized_nav_period_bundle(settings.database_path)

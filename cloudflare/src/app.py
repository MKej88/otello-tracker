from __future__ import annotations

from time import perf_counter

from fastapi import FastAPI, HTTPException, Query, Request, Response

from dashboard_hot_snapshot import (
    canonical_otec_quote,
    dashboard_bootstrap_payload,
    dashboard_hot_component,
    dashboard_hot_components,
    sync_otec_price,
)
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
    "/api/dashboard/bootstrap": ("public, max-age=15", "public, max-age=60, stale-while-revalidate=120"),
    "/api/dashboard/summary": ("public, max-age=15", "public, max-age=60, stale-while-revalidate=120"),
    "/api/dashboard/report-status": ("public, max-age=30", "public, max-age=120, stale-while-revalidate=300"),
    "/api/dashboard/runtime-status": ("public, max-age=15", "public, max-age=30, stale-while-revalidate=60"),
    "/api/dashboard/economic": ("public, max-age=15", "public, max-age=60, stale-while-revalidate=120"),
    "/api/dashboard/waterfall": ("public, max-age=15", "public, max-age=60, stale-while-revalidate=120"),
    "/api/dashboard/fx-backtest": ("public, max-age=1800", "public, max-age=21600, stale-while-revalidate=43200"),
    "/api/fx/dashboard": ("public, max-age=30", "public, max-age=60, stale-while-revalidate=120"),
    "/api/dashboard/history": ("public, max-age=300", "public, max-age=1800, stale-while-revalidate=3600"),
    "/api/dashboard/discount-history": ("public, max-age=300", "public, max-age=1800, stale-while-revalidate=3600"),
    "/api/dashboard/nav-periods": ("public, max-age=300", "public, max-age=1800, stale-while-revalidate=3600"),
    "/api/buybacks/forecast": ("public, max-age=300", "public, max-age=900, stale-while-revalidate=1800"),
    "/api/buybacks/dashboard": ("public, max-age=60", "public, max-age=300, stale-while-revalidate=600"),
    "/api/buybacks/overview-status": ("public, max-age=60", "public, max-age=300, stale-while-revalidate=600"),
    "/api/bemobi/dashboard": ("public, max-age=60", "public, max-age=300, stale-while-revalidate=600"),
    "/api/bemobi/consensus": ("public, max-age=300", "public, max-age=1800, stale-while-revalidate=3600"),
    "/api/bemobi/source-status": ("public, max-age=30", "public, max-age=120, stale-while-revalidate=300"),
    "/api/overview/events": ("public, max-age=60", "public, max-age=300, stale-while-revalidate=1800"),
    "/api/brazil/dashboard": ("public, max-age=300", "public, max-age=1800, stale-while-revalidate=3600"),
    "/api/news-events": ("public, max-age=60", "public, max-age=300, stale-while-revalidate=600"),
    "/api/market/quotes": ("public, max-age=30", "public, max-age=300, stale-while-revalidate=1800"),
    "/api/market/bemobi-after-oslo": ("public, max-age=15", "public, max-age=15"),
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
    # Timing begins at the first FastAPI middleware, before endpoint routing.
    # It does not include the ASGI adapter or Python isolate startup.
    fastapi_started = perf_counter()
    response = await call_next(request)
    for header, value in SECURITY_HEADERS.items():
        response.headers[header] = value
    browser_policy, edge_policy = CACHE_POLICIES.get(
        request.url.path, ("no-store", "no-store")
    )
    if request.url.path == "/api/brazil/dashboard" and (
        response.status_code >= 400 or getattr(request.state, "brazil_degraded", False)
    ):
        browser_policy = edge_policy = "no-store"
    response.headers["Cache-Control"] = browser_policy
    response.headers["Cloudflare-CDN-Cache-Control"] = edge_policy
    if request.url.path.startswith("/api/"):
        existing = response.headers.get("Server-Timing")
        measurement = f"otello_fastapi;dur={(perf_counter() - fastapi_started) * 1000:.2f}"
        response.headers["Server-Timing"] = (
            f"{existing}, {measurement}" if existing else measurement
        )
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


def _record_origin_read_timing(
    response: Response,
    repository: PerformanceD1Repository,
    started: float,
    import_ms: float,
    *,
    snapshot: str = "fallback",
) -> None:
    """Bounded response timing for troubleshooting cache MISS, without query contents.

    D1 time is accumulated across reads and may exceed handler wall time when
    independent requests run concurrently. Neither value includes network or
    time spent starting the Worker before this function is entered.
    """
    metrics = repository.performance_metrics()
    response.headers["Server-Timing"] = (
        f"otello_handler;dur={(perf_counter() - started) * 1000:.2f}, "
        f"otello_import;dur={import_ms:.2f}, "
        f"otello_d1;dur={metrics['d1_read_ms']:.2f}, "
        f"otello_reads;desc=\"{metrics['d1_reads']}\", "
        f"otello_snapshot;desc=\"{snapshot}\""
    )


@app.get("/api/health")
async def health(request: Request, response: Response) -> dict[str, str]:
    repository = _repository(request)
    d1_started = perf_counter()
    try:
        row = await repository.first("SELECT 1 AS ok")
    except Exception as exc:
        raise HTTPException(status_code=503, detail="D1 unavailable") from exc
    if row is None or int(row.get("ok", 0)) != 1:
        raise HTTPException(status_code=503, detail="D1 unavailable")
    # D1 time is server-side only; external TTFB also includes Worker startup and network.
    response.headers["Server-Timing"] = f"d1;dur={(perf_counter() - d1_started) * 1000:.2f}"
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
    cached, quotes = await dashboard_hot_components(repository, "summary", "quotes")
    if cached is not None:
        return sync_otec_price(cached, canonical_otec_quote(quotes or {}))
    from dashboard_service import dashboard_summary, enrich_dashboard_summary

    summary = await dashboard_summary(repository)
    summary = await enrich_dashboard_summary(summary, repository)
    from quote_details import market_quote_details

    quotes = await market_quote_details(repository)
    return sync_otec_price(summary, canonical_otec_quote(quotes))


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
    cached, quotes = await dashboard_hot_components(repository, "economic", "quotes")
    if cached is not None:
        return sync_otec_price(
            cached, canonical_otec_quote(quotes or {}), economic=True
        )
    from economic_nav_investor import economic_nav_summary

    payload = await economic_nav_summary(repository)
    from quote_details import market_quote_details

    quotes = await market_quote_details(repository)
    return sync_otec_price(payload, canonical_otec_quote(quotes), economic=True)


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


@app.get("/api/fx/dashboard")
async def get_fx_dashboard(request: Request) -> dict:
    from fx_dashboard import fx_dashboard

    return await fx_dashboard(_repository(request))


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


@app.get("/api/market/bemobi-after-oslo")
async def get_bemobi_after_oslo(request: Request) -> dict:
    from bemobi_after_oslo import bemobi_after_oslo

    return await bemobi_after_oslo(_repository(request))


@app.get("/api/buybacks/forecast")
async def get_buyback_forecast(
    request: Request,
    as_of_date: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> dict:
    repository = _repository(request)
    try:
        from buyback_service import buyback_forecast

        return await buyback_forecast(repository, as_of_date=as_of_date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid as_of_date") from exc


@app.get("/api/buybacks/dashboard")
async def get_buyback_dashboard(
    request: Request,
    response: Response,
    as_of_date: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> dict:
    from investor_snapshots import load_investor_snapshot

    started = perf_counter()
    repository = _repository(request)
    if as_of_date is None:
        cached = await load_investor_snapshot(repository, "buybacks_dashboard")
        if cached is not None:
            _record_origin_read_timing(response, repository, started, 0.0, snapshot="hit")
            return cached

    importing = perf_counter()
    from buyback_dashboard import buyback_dashboard
    import_ms = (perf_counter() - importing) * 1000
    try:
        payload = await buyback_dashboard(repository, as_of_date=as_of_date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid as_of_date") from exc
    _record_origin_read_timing(response, repository, started, import_ms)
    return payload


@app.get("/api/buybacks/overview-status")
async def get_buyback_overview_status(
    request: Request,
    as_of_date: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> dict:
    repository = _repository(request)
    try:
        if as_of_date is None:
            cached = await dashboard_hot_component(repository, "buyback")
            if cached is not None:
                return cached
        from buyback_dashboard import buyback_overview_status

        return await buyback_overview_status(repository, as_of_date=as_of_date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid as_of_date") from exc


@app.get("/api/bemobi/dashboard")
async def get_bemobi_dashboard(request: Request, response: Response) -> dict:
    from investor_snapshots import load_investor_snapshot

    started = perf_counter()
    repository = _repository(request)
    cached = await load_investor_snapshot(repository, "bemobi_dashboard")
    if cached is not None:
        _record_origin_read_timing(response, repository, started, 0.0, snapshot="hit")
        return cached

    importing = perf_counter()
    from bemobi_dashboard import bemobi_dashboard
    import_ms = (perf_counter() - importing) * 1000
    payload = await bemobi_dashboard(repository)
    _record_origin_read_timing(response, repository, started, import_ms)
    return payload


@app.get("/api/bemobi/consensus")
async def get_bemobi_consensus(request: Request, response: Response) -> dict:
    from investor_snapshots import load_investor_snapshot

    started = perf_counter()
    repository = _repository(request)
    cached = await load_investor_snapshot(repository, "bemobi_consensus")
    if cached is not None:
        _record_origin_read_timing(response, repository, started, 0.0, snapshot="hit")
        return cached

    importing = perf_counter()
    from bemobi_consensus_investor import bemobi_consensus
    import_ms = (perf_counter() - importing) * 1000
    payload = await bemobi_consensus(repository)
    _record_origin_read_timing(response, repository, started, import_ms)
    return payload


@app.get("/api/bemobi/source-status")
async def get_bemobi_source_status(request: Request) -> dict:
    from bemobi_source_status import bemobi_source_status

    return await bemobi_source_status(_repository(request))


@app.get("/api/overview/events")
async def get_overview_events(
    request: Request,
    as_of_date: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> dict:
    from overview_events import overview_events

    repository = _repository(request)
    try:
        if as_of_date is None:
            cached = await dashboard_hot_component(repository, "events")
            if cached is not None:
                return cached
        return await overview_events(repository, as_of_date=as_of_date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid as_of_date") from exc


@app.get("/api/brazil/dashboard")
async def get_brazil_dashboard(
    request: Request,
    response: Response,
    as_of_date: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> dict:
    from brazil_snapshot import cached_brazil_dashboard, snapshot_degraded

    started = perf_counter()
    diagnostics: dict[str, float | str] = {}
    try:
        payload = await cached_brazil_dashboard(
            _write_repository(request), as_of_date=as_of_date, diagnostics=diagnostics
        )
        request.state.brazil_degraded = snapshot_degraded(payload)
        # Server-Timing exposes only bounded aggregate durations and a fixed
        # snapshot category. It never includes SQL, row contents or source data.
        metrics = [f"brazil_handler;dur={(perf_counter() - started) * 1000:.2f}"]
        for key in ("d1", "parse"):
            elapsed = diagnostics.get(f"{key}_ms")
            if isinstance(elapsed, (float, int)):
                metrics.append(f"brazil_{key};dur={elapsed:.2f}")
        snapshot = diagnostics.get("snapshot")
        if snapshot in ("fresh", "stale", "missing", "historical"):
            metrics.append(f'brazil_snapshot;desc="{snapshot}"')
        response.headers["Server-Timing"] = ", ".join(metrics)
        return payload
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


@app.get("/api/bemobi-translations/{news_id}.pdf")
async def get_bemobi_translation(news_id: int, request: Request) -> Response:
    from bemobi_document_translation import is_safe_translated_key

    row = await _repository(request).first(
        """SELECT sd.translated_pdf_key, sd.translation_status
           FROM company_news cn JOIN source_documents sd ON sd.id=cn.source_document_id
           JOIN instruments i ON i.id=cn.issuer_instrument_id
           WHERE cn.id=? AND i.symbol='BMOB3' LIMIT 1""",
        (news_id,),
    )
    key = str(row.get("translated_pdf_key") or "") if row else ""
    if not row or row.get("translation_status") != "READY" or not is_safe_translated_key(key):
        raise HTTPException(status_code=404, detail="Norsk oversettelse er ikke tilgjengelig")
    env = request.scope.get("env")
    bucket = getattr(env, "SOURCE_ARCHIVE", None) if env is not None else None
    if bucket is None:
        raise HTTPException(status_code=503, detail="Dokumentlager er ikke tilgjengelig")
    stored = await bucket.get(key)
    if stored is None:
        raise HTTPException(status_code=404, detail="Norsk oversettelse er ikke tilgjengelig")
    payload = await stored.arrayBuffer()
    converter = getattr(payload, "to_py", None)
    content = bytes(converter()) if callable(converter) else bytes(payload)
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": 'inline; filename="bemobi-norsk.pdf"'},
    )

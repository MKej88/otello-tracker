from __future__ import annotations

import hashlib
import json
import urllib.parse
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo

try:
    from .bounded_response import read_response_bytes
    from .r2_archive import archive_bytes
except ImportError:
    from bounded_response import read_response_bytes
    from r2_archive import archive_bytes

YAHOO_QUERY1_BASE = "https://query1.finance.yahoo.com/v8/finance/chart"
YAHOO_QUERY2_BASE = "https://query2.finance.yahoo.com/v8/finance/chart"
YAHOO_CHART_BASES = (YAHOO_QUERY1_BASE, YAHOO_QUERY2_BASE)
YAHOO_CHART_BASE = YAHOO_QUERY1_BASE
SOURCE_CODE = "YAHOO_FINANCE"
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
D1_MAX_BOUND_PARAMETERS = 100
BOUND_PARAMETERS_PER_ROW = 8
WRITE_BATCH_ROWS = D1_MAX_BOUND_PARAMETERS // BOUND_PARAMETERS_PER_ROW
# Litt over tre kalendermåneder sikrer minst 63 normale handelssesjoner også
# rundt helgedager og børspauser.
RECENT_LOOKBACK_DAYS = 100
LIFE360_MAX_PRICE_AGE_DAYS = 7
LIFE360_HISTORY_ANCHOR_DAYS = 31
LIFE360_REQUIRED_SYMBOL = "LIF"
LIFE360_CONTROL_SYMBOLS = {"360.AX"}
LIFE360_SERIES = {
    "360.AX": {
        "provider_symbol": "360.AX",
        "currency": "AUD",
        "listing_date": "2019-05-10",
        "role": "ASX_CDI",
    },
    "LIF": {
        "provider_symbol": "LIF",
        "currency": "USD",
        "listing_date": "2024-06-06",
        "role": "NASDAQ_COMMON",
    },
}


def _epoch(day: date) -> int:
    return int(datetime.combine(day, time.min, tzinfo=UTC).timestamp())


def _provider_symbol(provider_symbol: str) -> str:
    """Return only one of the two literal provider symbols we support."""
    if provider_symbol == "LIF":
        return "LIF"
    if provider_symbol == "360.AX":
        return "360.AX"
    raise ValueError(f"Ikke tillatt Yahoo-symbol: {provider_symbol!r}")


def _endpoint_base(endpoint: int) -> str:
    """Map an internal endpoint id to a fixed Yahoo origin."""
    if endpoint == 1:
        return YAHOO_QUERY1_BASE
    if endpoint == 2:
        return YAHOO_QUERY2_BASE
    raise ValueError(f"Ukjent Yahoo-endepunkt: {endpoint}")


def _build_yahoo_chart_url(
    endpoint: int,
    provider_symbol: str,
    start_date: str,
    end_date: str,
) -> str:
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date) + timedelta(days=1)
    query = urllib.parse.urlencode(
        {
            "period1": _epoch(start),
            "period2": _epoch(end),
            "interval": "1d",
            "events": "history",
            "includeAdjustedClose": "false",
        }
    )
    symbol = urllib.parse.quote(_provider_symbol(provider_symbol), safe="")
    return f"{_endpoint_base(endpoint)}/{symbol}?{query}"


def build_yahoo_chart_url(provider_symbol: str, start_date: str, end_date: str) -> str:
    """Build the canonical query1 URL; callers cannot choose an arbitrary origin."""
    return _build_yahoo_chart_url(1, provider_symbol, start_date, end_date)


def parse_yahoo_chart(
    payload: bytes | str | dict[str, Any],
    *,
    expected_symbol: str,
    expected_currency: str,
) -> dict[str, Any]:
    if isinstance(payload, bytes):
        parsed = json.loads(payload.decode("utf-8-sig"))
    elif isinstance(payload, str):
        parsed = json.loads(payload)
    else:
        parsed = payload
    if not isinstance(parsed, dict):
        raise ValueError("Yahoo-returneringen er ikke et JSON-objekt")

    chart = parsed.get("chart")
    if not isinstance(chart, dict):
        raise ValueError("Yahoo-returneringen mangler chart")
    if chart.get("error"):
        raise ValueError(f"Yahoo-returneringen inneholder feil: {chart.get('error')}")
    results = chart.get("result")
    if (
        not isinstance(results, list)
        or len(results) != 1
        or not isinstance(results[0], dict)
    ):
        raise ValueError("Yahoo-returneringen mangler én entydig resultatserie")

    result = results[0]
    meta = result.get("meta")
    if not isinstance(meta, dict):
        raise ValueError("Yahoo-returneringen mangler metadata")
    symbol = str(meta.get("symbol") or "")
    currency = str(meta.get("currency") or "")
    if symbol != expected_symbol:
        raise ValueError(
            f"Yahoo-symbol {symbol!r} matcher ikke forventet {expected_symbol!r}"
        )
    if currency != expected_currency:
        raise ValueError(
            f"Yahoo-valuta {currency!r} matcher ikke forventet {expected_currency!r}"
        )

    timezone_name = str(meta.get("exchangeTimezoneName") or "UTC")
    try:
        exchange_tz = ZoneInfo(timezone_name)
    except (KeyError, ValueError):
        exchange_tz = UTC
        timezone_name = "UTC"

    timestamps = result.get("timestamp")
    indicators = result.get("indicators")
    quote_rows = indicators.get("quote") if isinstance(indicators, dict) else None
    if (
        not isinstance(timestamps, list)
        or not isinstance(quote_rows, list)
        or len(quote_rows) != 1
    ):
        raise ValueError("Yahoo-returneringen mangler daglige timestamps/quote")
    quote = quote_rows[0] if isinstance(quote_rows[0], dict) else {}
    closes = quote.get("close")
    if not isinstance(closes, list) or len(closes) != len(timestamps):
        raise ValueError("Yahoo close-serien matcher ikke timestamp-serien")

    rows: list[dict[str, str]] = []
    previous_timestamp: int | None = None
    optional_series = {
        "open": quote.get("open"),
        "low": quote.get("low"),
        "high": quote.get("high"),
        "volume": quote.get("volume"),
    }
    for name, values in optional_series.items():
        if values is not None and (
            not isinstance(values, list) or len(values) != len(timestamps)
        ):
            raise ValueError(f"Yahoo {name}-serien matcher ikke timestamp-serien")

    for index, (raw_timestamp, raw_close) in enumerate(
        zip(timestamps, closes, strict=True)
    ):
        if raw_close is None:
            continue
        try:
            timestamp = int(raw_timestamp)
            price = Decimal(str(raw_close))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError(
                "Yahoo-serien inneholder ugyldig timestamp eller sluttkurs"
            ) from exc
        if previous_timestamp is not None and timestamp <= previous_timestamp:
            raise ValueError("Yahoo-timestamps er ikke strengt stigende")
        previous_timestamp = timestamp
        if not price.is_finite() or price <= 0 or price > Decimal("100000"):
            raise ValueError(f"Yahoo-serien inneholder urimelig sluttkurs: {price}")
        observed = datetime.fromtimestamp(timestamp, tz=UTC)
        trading_date = observed.astimezone(exchange_tz).date().isoformat()
        row = {
            "trading_date": trading_date,
            "observed_at": observed.isoformat(timespec="seconds").replace(
                "+00:00", "Z"
            ),
            "price": format(price, "f"),
        }
        for name, values in optional_series.items():
            raw_value = values[index] if isinstance(values, list) else None
            if raw_value is None:
                continue
            try:
                value = Decimal(str(raw_value))
            except (InvalidOperation, TypeError, ValueError) as exc:
                raise ValueError(f"Yahoo-serien inneholder ugyldig {name}") from exc
            if not value.is_finite() or value < 0:
                raise ValueError(f"Yahoo-serien inneholder urimelig {name}: {value}")
            if name != "volume" and value == 0:
                raise ValueError(f"Yahoo-serien inneholder urimelig {name}: {value}")
            row[name] = format(value, "f")
        rows.append(row)

    if not rows:
        raise ValueError("Yahoo-returneringen inneholdt ingen gyldige sluttkurser")
    return {
        "symbol": symbol,
        "currency": currency,
        "exchange_name": str(meta.get("exchangeName") or ""),
        "exchange_timezone": timezone_name,
        "rows": rows,
    }


async def _download_chart_endpoint(
    endpoint: int,
    provider_symbol: str,
    start_date: str,
    end_date: str,
    *,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> tuple[str, bytes, str]:
    if fetcher is None:
        from workers import fetch

        fetcher = fetch
    url = _build_yahoo_chart_url(endpoint, provider_symbol, start_date, end_date)
    response = await fetcher(
        url,
        headers={
            "Accept": "application/json,*/*;q=0.8",
            "User-Agent": "OtelloTracker/1.0 (+https://otellotracker.com)",
        },
    )
    if not bool(getattr(response, "ok", False)):
        raise RuntimeError(
            f"Yahoo Finance feilet med HTTP {getattr(response, 'status', 'unknown')}"
        )
    payload = await read_response_bytes(
        response,
        max_bytes=MAX_RESPONSE_BYTES,
        label="Yahoo Finance chart JSON",
    )
    return url, payload, _endpoint_base(endpoint)


async def _download_chart_with_host_fallback(
    provider_symbol: str,
    start_date: str,
    end_date: str,
    *,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> tuple[str, bytes, str]:
    failures: list[str] = []
    for endpoint in (1, 2):
        try:
            return await _download_chart_endpoint(
                endpoint,
                provider_symbol,
                start_date,
                end_date,
                fetcher=fetcher,
            )
        except Exception as exc:
            base_url = _endpoint_base(endpoint)
            failures.append(
                f"{urllib.parse.urlsplit(base_url).netloc}: {str(exc)[:300]}"
            )
    raise RuntimeError(
        "Yahoo Finance chart feilet på alle endepunkter: " + "; ".join(failures)
    )


def _is_yahoo_transport_failure(exc: Exception) -> bool:
    return isinstance(exc, RuntimeError) and str(exc).startswith(
        "Yahoo Finance chart feilet på alle endepunkter:"
    )


async def _coverage(repository, symbol: str) -> dict[str, Any]:
    row = await repository.first(
        """
        SELECT COUNT(*) AS n, MIN(mp.trading_date) AS min_date, MAX(mp.trading_date) AS max_date
        FROM market_prices mp
        JOIN instruments i ON i.id=mp.instrument_id
        JOIN sources s ON s.id=mp.source_id
        WHERE i.symbol=? AND s.code=? AND mp.price_type='CLOSE'
        """,
        (symbol, SOURCE_CODE),
    )
    return dict(row or {"n": 0, "min_date": None, "max_date": None})


async def _last_good_lif_price(repository) -> dict[str, Any] | None:
    row = await repository.first(
        """
        SELECT mp.trading_date, mp.observed_at, mp.price, mp.currency,
               s.code AS source_code
        FROM market_prices mp
        JOIN instruments i ON i.id=mp.instrument_id
        JOIN sources s ON s.id=mp.source_id
        WHERE i.symbol=? AND mp.price_type='CLOSE'
        ORDER BY mp.trading_date DESC, mp.observed_at DESC, mp.id DESC
        LIMIT 1
        """,
        (LIFE360_REQUIRED_SYMBOL,),
    )
    return dict(row) if row else None


async def _lif_price_for_history_anchor(
    repository, as_of_date: str
) -> dict[str, Any] | None:
    floor = (
        date.fromisoformat(as_of_date) - timedelta(days=LIFE360_MAX_PRICE_AGE_DAYS)
    ).isoformat()
    row = await repository.first(
        """
        SELECT mp.trading_date, mp.observed_at, mp.price, mp.currency,
               s.code AS source_code
        FROM market_prices mp
        JOIN instruments i ON i.id=mp.instrument_id
        JOIN sources s ON s.id=mp.source_id
        WHERE i.symbol=? AND mp.currency='USD'
          AND mp.price_type IN ('CLOSE','LAST')
          AND mp.trading_date <= ? AND mp.trading_date >= ?
        ORDER BY mp.trading_date DESC,
                 CASE s.code WHEN 'YAHOO_FINANCE' THEN 0 WHEN 'LIFE360_IR_LSEG' THEN 1 ELSE 5 END,
                 CASE mp.price_type WHEN 'CLOSE' THEN 0 ELSE 1 END,
                 mp.observed_at DESC, mp.id DESC
        LIMIT 1
        """,
        (LIFE360_REQUIRED_SYMBOL, as_of_date, floor),
    )
    return dict(row) if row else None


async def repair_life360_lif_if_stale(
    repository,
    *,
    target_date: str,
    archive_bucket: Any | None = None,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Repair missing LIF data, or refresh it explicitly for the 30-minute job."""
    target = date.fromisoformat(target_date)
    history_anchor_date = (
        target - timedelta(days=LIFE360_HISTORY_ANCHOR_DAYS)
    ).isoformat()
    before = await _last_good_lif_price(repository)
    before_anchor = await _lif_price_for_history_anchor(repository, history_anchor_date)
    before_date_raw = str((before or {}).get("trading_date") or "")
    before_date = date.fromisoformat(before_date_raw) if before_date_raw else None
    age_days = (target - before_date).days if before_date is not None else None
    latest_fresh = age_days is not None and 0 <= age_days <= LIFE360_MAX_PRICE_AGE_DAYS
    history_anchor_ready = before_anchor is not None
    if latest_fresh and history_anchor_ready and not force_refresh:
        return {
            "status": "skipped",
            "reason": "lif_price_fresh",
            "target_date": target_date,
            "latest_price_date": before_date_raw,
            "age_days": age_days,
            "history_anchor_date": history_anchor_date,
            "history_anchor_price_date": str(before_anchor.get("trading_date") or "")
            or None,
            "network_fetches_avoided": True,
            "rows_written": 0,
            "repaired": False,
        }

    result = await _refresh_lif_with_independent_fallback(
        repository,
        target_date=target_date,
        archive_bucket=archive_bucket,
        fetcher=fetcher,
    )
    after = await _last_good_lif_price(repository)
    after_anchor = await _lif_price_for_history_anchor(repository, history_anchor_date)
    after_date_raw = str((after or {}).get("trading_date") or "")
    after_date = date.fromisoformat(after_date_raw) if after_date_raw else None
    after_age_days = (target - after_date).days if after_date is not None else None
    latest_repaired = (
        after_age_days is not None and 0 <= after_age_days <= LIFE360_MAX_PRICE_AGE_DAYS
    )
    history_anchor_repaired = after_anchor is not None
    repaired = bool(latest_repaired and history_anchor_repaired)
    reason = None
    if not latest_repaired:
        reason = "lif_price_still_stale"
    elif not history_anchor_repaired:
        reason = "lif_1m_anchor_still_missing"
    return {
        "status": "ok" if repaired else "partial",
        "reason": reason,
        "target_date": target_date,
        "previous_price_date": before_date_raw or None,
        "latest_price_date": after_date_raw or None,
        "age_days": after_age_days,
        "history_anchor_date": history_anchor_date,
        "previous_history_anchor_price_date": (
            str(before_anchor.get("trading_date") or "") or None
            if before_anchor
            else None
        ),
        "history_anchor_price_date": (
            str(after_anchor.get("trading_date") or "") or None
            if after_anchor
            else None
        ),
        "network_fetches_avoided": False,
        "rows_written": int(result.get("rows_written") or 0),
        "repaired": repaired,
        "source_result": result,
    }


async def _write_rows(
    repository,
    *,
    symbol: str,
    currency: str,
    rows: list[dict[str, str]],
    document_id: int,
    role: str,
) -> int:
    source_id = await repository.source_id(SOURCE_CODE)
    instrument_id = await repository.instrument_id(symbol)
    written = 0
    for offset in range(0, len(rows), WRITE_BATCH_ROWS):
        chunk = rows[offset : offset + WRITE_BATCH_ROWS]
        values_sql = ",".join(
            "(?, ?, ?, 'CLOSE', ?, ?, ?, ?, 'DIRECT', ?)" for _ in chunk
        )
        parameters: list[Any] = []
        for row in chunk:
            metadata = json.dumps(
                {
                    "provider": "Yahoo Finance",
                    "provider_symbol": LIFE360_SERIES[symbol]["provider_symbol"],
                    "role": role,
                    "adjusted": False,
                    "source_policy": "UNOFFICIAL_SECONDARY_LAST_GOOD",
                    "open": row.get("open"),
                    "low": row.get("low"),
                    "high": row.get("high"),
                    "volume_shares": row.get("volume"),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            parameters.extend(
                (
                    instrument_id,
                    row["observed_at"],
                    row["trading_date"],
                    row["price"],
                    currency,
                    source_id,
                    document_id,
                    metadata,
                )
            )
        await repository.run(
            f"""
            INSERT INTO market_prices(
                instrument_id, observed_at, trading_date, price_type, price, currency,
                source_id, source_document_id, quality, metadata_json
            ) VALUES {values_sql}
            ON CONFLICT(instrument_id, observed_at, price_type, source_id)
            DO UPDATE SET
                trading_date=excluded.trading_date,
                price=excluded.price,
                currency=excluded.currency,
                source_document_id=excluded.source_document_id,
                quality=excluded.quality,
                metadata_json=excluded.metadata_json
            """,
            tuple(parameters),
        )
        written += len(chunk)
    return written


async def _refresh_symbol(
    repository,
    *,
    symbol: str,
    target_date: str,
    archive_bucket: Any | None,
    fetcher: Callable[..., Awaitable[Any]] | None,
) -> dict[str, Any]:
    config = LIFE360_SERIES[symbol]
    target = date.fromisoformat(target_date)
    listing = date.fromisoformat(str(config["listing_date"]))
    coverage = await _coverage(repository, symbol)
    min_date = str(coverage.get("min_date") or "")
    max_date = str(coverage.get("max_date") or "")
    history_backfill = not min_date or date.fromisoformat(
        min_date
    ) > listing + timedelta(days=7)
    if history_backfill:
        start = listing
    elif max_date:
        start = max(
            listing, date.fromisoformat(max_date) - timedelta(days=RECENT_LOOKBACK_DAYS)
        )
    else:
        start = max(listing, target - timedelta(days=RECENT_LOOKBACK_DAYS))
    if start > target:
        start = target

    url, payload, provider_base = await _download_chart_with_host_fallback(
        str(config["provider_symbol"]),
        start.isoformat(),
        target_date,
        fetcher=fetcher,
    )
    parsed = parse_yahoo_chart(
        payload,
        expected_symbol=str(config["provider_symbol"]),
        expected_currency=str(config["currency"]),
    )
    digest = hashlib.sha256(payload).hexdigest()
    archived = (
        await archive_bytes(
            archive_bucket,
            payload,
            source="yahoo-finance",
            kind="life360-chart",
            logical_date=target_date,
            filename=f"{symbol.replace('.', '-')}-{start.isoformat()}-{target_date}-{digest[:12]}.json",
        )
        if archive_bucket is not None
        else None
    )
    document_id = await repository.create_source_document(
        source_code=SOURCE_CODE,
        external_id=f"life360-chart:{symbol}:{start.isoformat()}:{target_date}",
        document_type="API_RESPONSE",
        title=f"Life360 {symbol} daily unadjusted closes from Yahoo Finance",
        url=url,
        published_at=f"{target_date}T00:00:00Z",
        content_sha256=digest,
        metadata={
            "symbol": symbol,
            "provider_symbol": config["provider_symbol"],
            "provider_endpoint": provider_base,
            "provider_endpoints": list(YAHOO_CHART_BASES),
            "currency": config["currency"],
            "role": config["role"],
            "from": start.isoformat(),
            "to": target_date,
            "history_backfill": history_backfill,
            "exchange_name": parsed["exchange_name"],
            "exchange_timezone": parsed["exchange_timezone"],
            "price_type": "unadjusted_close",
            "source_policy": "UNOFFICIAL_SECONDARY_LAST_GOOD",
            "r2_key": archived.get("r2_key") if archived else None,
            "control_sources": [
                "https://investors.life360.com/stock-information/historic-price-lookup",
                "https://investors.life360.com/stock-information/stock-quote-chart/nasdaq",
                "https://www.nasdaq.com/market-activity/stocks/lif",
            ],
        },
    )
    rows = [
        row
        for row in parsed["rows"]
        if str(config["listing_date"]) <= row["trading_date"] <= target_date
    ]
    written = await _write_rows(
        repository,
        symbol=symbol,
        currency=str(config["currency"]),
        rows=rows,
        document_id=document_id,
        role=str(config["role"]),
    )
    return {
        "status": "ok",
        "symbol": symbol,
        "provider_symbol": config["provider_symbol"],
        "provider_endpoint": provider_base,
        "currency": config["currency"],
        "from": start.isoformat(),
        "to": target_date,
        "rows_written": written,
        "write_batches": (written + WRITE_BATCH_ROWS - 1) // WRITE_BATCH_ROWS,
        "history_backfill": history_backfill,
        "first_price_date": rows[0]["trading_date"] if rows else None,
        "last_price_date": rows[-1]["trading_date"] if rows else None,
        "source_document_id": document_id,
        "content_sha256": digest,
        "r2_archive": archived,
    }


async def _refresh_lif_with_independent_fallback(
    repository,
    *,
    target_date: str,
    archive_bucket: Any | None,
    fetcher: Callable[..., Awaitable[Any]] | None,
) -> dict[str, Any]:
    try:
        return await _refresh_symbol(
            repository,
            symbol=LIFE360_REQUIRED_SYMBOL,
            target_date=target_date,
            archive_bucket=archive_bucket,
            fetcher=fetcher,
        )
    except Exception as yahoo_exc:
        if not _is_yahoo_transport_failure(yahoo_exc):
            raise
        try:
            from .life360_ir_lseg import refresh_life360_ir_lif
        except ImportError:
            from life360_ir_lseg import refresh_life360_ir_lif

        try:
            fallback = await refresh_life360_ir_lif(
                repository,
                target_date=target_date,
                archive_bucket=archive_bucket,
                fetcher=fetcher,
            )
        except Exception as fallback_exc:
            raise RuntimeError(
                "Life360 LIF kunne ikke oppdateres. "
                f"Yahoo Finance: {str(yahoo_exc)[:600]}; "
                "Life360 IR/LSEG fallback: "
                f"{type(fallback_exc).__name__}: {str(fallback_exc)[:300]}"
            ) from fallback_exc
        return {
            **fallback,
            "fallback_used": True,
            "fallback_from": SOURCE_CODE,
            "fallback_reason": str(yahoo_exc)[:1000],
        }


async def refresh_life360_market_data(
    repository,
    *,
    target_date: str,
    archive_bucket: Any | None = None,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> dict[str, Any]:
    results: dict[str, dict[str, Any]] = {}
    required_errors: list[dict[str, str]] = []
    control_errors: list[dict[str, str]] = []
    total_written = 0
    history_backfill = False

    try:
        lif_result = await _refresh_lif_with_independent_fallback(
            repository,
            target_date=target_date,
            archive_bucket=archive_bucket,
            fetcher=fetcher,
        )
    except Exception as exc:
        lif_result = {
            "status": "error",
            "symbol": LIFE360_REQUIRED_SYMBOL,
            "error": str(exc)[:1000],
            "error_type": type(exc).__name__,
        }
        required_errors.append(
            {"symbol": LIFE360_REQUIRED_SYMBOL, "error": str(exc)[:1000]}
        )
    results[LIFE360_REQUIRED_SYMBOL] = lif_result
    total_written += int(lif_result.get("rows_written") or 0)
    history_backfill = history_backfill or bool(lif_result.get("history_backfill"))

    for symbol in sorted(LIFE360_CONTROL_SYMBOLS):
        try:
            result = await _refresh_symbol(
                repository,
                symbol=symbol,
                target_date=target_date,
                archive_bucket=archive_bucket,
                fetcher=fetcher,
            )
        except Exception as exc:
            result = {
                "status": "error",
                "symbol": symbol,
                "error": str(exc)[:1000],
                "error_type": type(exc).__name__,
            }
            control_errors.append({"symbol": symbol, "error": str(exc)[:1000]})
        results[symbol] = result
        total_written += int(result.get("rows_written") or 0)
        history_backfill = history_backfill or bool(result.get("history_backfill"))

    try:
        last_good_lif = await _last_good_lif_price(repository)
    except Exception as exc:
        last_good_lif = {"lookup_error": str(exc)[:500]}

    lif_ready = results.get(LIFE360_REQUIRED_SYMBOL, {}).get("status") == "ok"
    control_ready = all(
        results.get(symbol, {}).get("status") == "ok"
        for symbol in LIFE360_CONTROL_SYMBOLS
    )
    fallback_used = bool(results.get(LIFE360_REQUIRED_SYMBOL, {}).get("fallback_used"))
    return {
        "status": "ok" if lif_ready else "error",
        "provider": "Life360 IR/LSEG" if fallback_used else "Yahoo Finance",
        "provider_endpoints": list(YAHOO_CHART_BASES),
        "source_policy": (
            "INDEPENDENT_SECONDARY_FALLBACK"
            if fallback_used
            else "UNOFFICIAL_SECONDARY_LAST_GOOD"
        ),
        "fallback_used": fallback_used,
        "target_date": target_date,
        "rows_written": total_written,
        "history_backfill": history_backfill,
        "required_series": LIFE360_REQUIRED_SYMBOL,
        "control_series": sorted(LIFE360_CONTROL_SYMBOLS),
        "control_status": "ok" if control_ready else "degraded",
        "series": results,
        "last_good_lif": last_good_lif,
        "errors": required_errors,
        "control_errors": control_errors,
    }

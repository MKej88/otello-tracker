from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, time as dt_time
from decimal import Decimal
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo

try:
    from .bounded_response import read_response_bytes
    from .oslo_calendar import is_oslo_bors_trading_day
    from .otec_ingestion import (
        DOWNLOAD_URL,
        FILE_TYPE,
        MAX_RECOVERY_ZIP_BYTES,
        OTEC_SYMBOL,
        TRADING_LOCATION,
        parse_euronext_recovery_trades,
    )
except ImportError:
    from bounded_response import read_response_bytes
    from oslo_calendar import is_oslo_bors_trading_day
    from otec_ingestion import (
        DOWNLOAD_URL,
        FILE_TYPE,
        MAX_RECOVERY_ZIP_BYTES,
        OTEC_SYMBOL,
        TRADING_LOCATION,
        parse_euronext_recovery_trades,
    )

OSLO_TZ = ZoneInfo("Europe/Oslo")
PREVIOUS_DAY_SELECTION = "PREVIOUS_TRADING_DAY"
CURRENT_DAY_SELECTION = "CURRENT_TRADING_DAY"
ACTIVITY_EOD_AFTER = dt_time(16, 45)


def _as_oslo_datetime(value: datetime | None) -> datetime:
    current = value or datetime.now(OSLO_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=OSLO_TZ)
    return current.astimezone(OSLO_TZ)


def _previous_trading_day(day):
    candidate = day - timedelta(days=1)
    for _ in range(10):
        if is_oslo_bors_trading_day(candidate):
            return candidate
        candidate -= timedelta(days=1)
    raise RuntimeError(f"Fant ikke forrige Oslo Børs-handelsdag før {day.isoformat()}")


def _activity_url(selection: str) -> str:
    normalized = selection.strip().upper()
    if normalized not in {PREVIOUS_DAY_SELECTION, CURRENT_DAY_SELECTION}:
        raise ValueError(f"Ugyldig Euronext aktivitets-selection: {selection}")
    return DOWNLOAD_URL.format(
        file_type=FILE_TYPE,
        time_selection=normalized,
        trading_location=TRADING_LOCATION,
    )


async def _download_activity(
    selection: str,
    *,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> tuple[str, bytes]:
    url = _activity_url(selection)
    if fetcher is None:
        from workers import fetch

        fetcher = fetch
    response = await fetcher(
        url,
        headers={
            "User-Agent": "otello-tracker/1.0 private-investor-dashboard",
            "Accept": "application/zip,application/octet-stream,*/*;q=0.8",
        },
    )
    if not bool(getattr(response, "ok", False)):
        status = getattr(response, "status", "unknown")
        raise RuntimeError(f"Euronext OTEC dagsvolum feilet med HTTP {status}")
    payload = await read_response_bytes(
        response,
        max_bytes=MAX_RECOVERY_ZIP_BYTES,
        label=f"Euronext OTEC dagsvolum {selection}",
    )
    return url, payload


async def _official_activity_exists(repository, target_date: str) -> bool:
    row = await repository.first(
        """
        SELECT 1 AS ok
        FROM market_activity ma
        JOIN instruments i ON i.id=ma.instrument_id
        JOIN sources s ON s.id=ma.source_id
        WHERE i.symbol='OTEC' AND ma.trading_date=? AND s.code='EURONEXT'
        LIMIT 1
        """,
        (target_date,),
    )
    return row is not None


async def ingest_otec_daily_activity(
    repository,
    payload: bytes,
    *,
    selection: str,
    source_url: str,
    target_date: str,
) -> dict[str, Any]:
    """Aggregate one finalized Euronext daily file to a single OTEC market_activity row."""
    trades = [
        item for item in parse_euronext_recovery_trades(payload)
        if item.trading_date == target_date
    ]
    if not trades:
        return {
            "status": "no_trade",
            "target_date": target_date,
            "selection": selection,
            "source_url": source_url,
        }

    quantity = sum((item.quantity for item in trades), Decimal("0"))
    if quantity != quantity.to_integral_value() or quantity < 0:
        raise ValueError(f"Ugyldig OTEC dagsvolum fra Euronext: {quantity}")
    latest = max(
        trades,
        key=lambda item: (
            item.trading_datetime,
            item.publication_datetime,
            item.trade_unique_identifier,
        ),
    )
    volume_shares = int(quantity)
    digest = hashlib.sha256(payload).hexdigest()
    metadata = {
        "feed": "DELAYED_PUBLIC_TRADE_FILE",
        "feed_mode": "DAILY_ACTIVITY",
        "time_selection": selection,
        "trading_location": TRADING_LOCATION,
        "target_date": target_date,
        "aggregation": "sum MifidQuantity for exact OTEC/XOSL/MONE/NOK trades",
        "trade_rows": len(trades),
        "latest_trade_at": latest.trading_datetime,
        "latest_trade_price_nok": format(latest.price, "f"),
        "source_quality": "OFFICIAL_DELAYED_TRADE_FILE",
    }
    document_id = await repository.create_source_document(
        source_code="EURONEXT",
        external_id=f"otec-activity-{selection.lower()}-{target_date}-{digest[:20]}",
        document_type="DELAYED_MARKET_ACTIVITY_FILE",
        title=f"Euronext {selection} OTEC daily activity {target_date}",
        url=source_url,
        published_at=latest.publication_datetime,
        content_sha256=digest,
        metadata=metadata,
    )
    instrument_id = await repository.instrument_id(OTEC_SYMBOL)
    source_id = await repository.source_id("EURONEXT")
    await repository.run(
        """
        INSERT INTO market_activity(
            instrument_id, trading_date, volume_shares, last_price_nok,
            source_id, source_document_id, quality, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, 'DELAYED_TRADE_SUM', ?)
        ON CONFLICT(instrument_id, trading_date, source_id) DO UPDATE SET
            volume_shares=excluded.volume_shares,
            last_price_nok=excluded.last_price_nok,
            source_document_id=excluded.source_document_id,
            quality=excluded.quality,
            metadata_json=excluded.metadata_json,
            updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
        """,
        (
            instrument_id,
            target_date,
            volume_shares,
            format(latest.price, "f"),
            source_id,
            document_id,
            json.dumps(metadata, ensure_ascii=False, sort_keys=True),
        ),
    )

    # A one-time secondary backfill may cover a date before official activity becomes
    # available. Once Euronext has supplied the same date, remove only that explicit
    # fallback row so downstream daily-volume sums can never double count the session.
    fallback = await repository.first("SELECT id FROM sources WHERE code='FT_MARKETS' LIMIT 1")
    replaced_fallback = False
    if fallback is not None:
        existing = await repository.first(
            """
            SELECT 1 AS ok FROM market_activity
            WHERE instrument_id=? AND trading_date=? AND source_id=? LIMIT 1
            """,
            (instrument_id, target_date, int(fallback["id"])),
        )
        if existing is not None:
            await repository.run(
                "DELETE FROM market_activity WHERE instrument_id=? AND trading_date=? AND source_id=?",
                (instrument_id, target_date, int(fallback["id"])),
            )
            replaced_fallback = True

    return {
        "status": "ok",
        "target_date": target_date,
        "selection": selection,
        "volume_shares": volume_shares,
        "last_price_nok": format(latest.price, "f"),
        "trade_rows": len(trades),
        "source_document_id": document_id,
        "replaced_secondary_fallback": replaced_fallback,
        "source_url": source_url,
    }


async def refresh_otec_daily_activity(
    repository,
    *,
    now: datetime | None = None,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> dict[str, Any]:
    """Repair yesterday once, then persist today's finalized activity after Oslo close."""
    local = _as_oslo_datetime(now)
    attempts: list[dict[str, Any]] = []
    written = 0

    previous = _previous_trading_day(local.date()).isoformat()
    if not await _official_activity_exists(repository, previous):
        url, payload = await _download_activity(PREVIOUS_DAY_SELECTION, fetcher=fetcher)
        result = await ingest_otec_daily_activity(
            repository,
            payload,
            selection=PREVIOUS_DAY_SELECTION,
            source_url=url,
            target_date=previous,
        )
        attempts.append(result)
        written += int(result.get("status") == "ok")
    else:
        attempts.append({
            "status": "skipped",
            "reason": "previous_day_already_stored",
            "target_date": previous,
        })

    today = local.date()
    local_time = local.time().replace(tzinfo=None)
    if is_oslo_bors_trading_day(today) and local_time >= ACTIVITY_EOD_AFTER:
        target = today.isoformat()
        if not await _official_activity_exists(repository, target):
            url, payload = await _download_activity(CURRENT_DAY_SELECTION, fetcher=fetcher)
            result = await ingest_otec_daily_activity(
                repository,
                payload,
                selection=CURRENT_DAY_SELECTION,
                source_url=url,
                target_date=target,
            )
            attempts.append(result)
            written += int(result.get("status") == "ok")
        else:
            attempts.append({
                "status": "skipped",
                "reason": "current_day_already_stored",
                "target_date": target,
            })

    return {
        "status": "ok" if written or all(item.get("status") == "skipped" for item in attempts) else "no_trade",
        "written": written,
        "attempts": attempts,
        "as_of": local.isoformat(),
    }

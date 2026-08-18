from __future__ import annotations

import hashlib
from datetime import date
from typing import Any, Awaitable, Callable

try:
    from .bounded_response import read_response_buffer
    from .oslo_calendar import is_oslo_bors_trading_day
    from .otec_ingestion import (
        FILE_TYPE,
        FULL_DAY_SELECTION,
        OTEC_ISIN,
        OTEC_SYMBOL,
        TRADING_LOCATION,
        _latest_trade,
        _parse_euronext_trades,
        delayed_download_url,
        eod_otec_check_done,
        finalize_otec_eod_from_coverage,
    )
except ImportError:
    from bounded_response import read_response_buffer
    from oslo_calendar import is_oslo_bors_trading_day
    from otec_ingestion import (
        FILE_TYPE,
        FULL_DAY_SELECTION,
        OTEC_ISIN,
        OTEC_SYMBOL,
        TRADING_LOCATION,
        _latest_trade,
        _parse_euronext_trades,
        delayed_download_url,
        eod_otec_check_done,
        finalize_otec_eod_from_coverage,
    )

# Full-day recovery is an exceptional path, not a reason to run near the 128 MiB Worker
# memory ceiling. Keep the compressed payload small enough that one temporary immutable
# R2 upload copy or one BytesIO ZIP view still leaves substantial runtime headroom.
MAX_WORKFLOW_ZIP_BYTES = 28 * 1024 * 1024
MAX_WORKFLOW_CSV_BYTES = 384 * 1024 * 1024


async def _download(
    *,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> tuple[str, bytearray]:
    if fetcher is None:
        from workers import fetch

        fetcher = fetch
    url = delayed_download_url(FULL_DAY_SELECTION)
    response = await fetcher(
        url,
        headers={
            "Accept": "application/zip,application/octet-stream,*/*;q=0.8",
            "User-Agent": "otello-tracker/1.0 private-investor-dashboard",
        },
    )
    if not bool(getattr(response, "ok", False)):
        raise RuntimeError(
            f"Euronext Workflow recovery feilet med HTTP {getattr(response, 'status', 'unknown')}"
        )
    payload = await read_response_buffer(
        response,
        max_bytes=MAX_WORKFLOW_ZIP_BYTES,
        label="Euronext Workflow recovery ZIP",
    )
    return url, payload


async def recover_otec_to_r2(
    repository,
    archive_bucket,
    *,
    target_date: str,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> dict[str, Any]:
    """Recover one full Euronext session with a conservative memory envelope.

    The compressed response is accumulated in one mutable buffer. The short-lived bytes
    copy needed by the R2 Python binding is uploaded and released before ZIP parsing, so
    the upload representation and the parser's random-access view do not overlap.
    """
    url, payload = await _download(fetcher=fetcher)
    digest = hashlib.sha256(payload).hexdigest()
    r2_key = f"raw/euronext/otec/{target_date}/current-trading-day-{digest[:20]}.zip"

    upload_payload = bytes(payload)
    try:
        await archive_bucket.put(r2_key, upload_payload)
    finally:
        del upload_payload

    trades = _parse_euronext_trades(
        payload,
        max_zip_bytes=MAX_WORKFLOW_ZIP_BYTES,
        max_csv_bytes=MAX_WORKFLOW_CSV_BYTES,
        payload_label="workflow-recovery",
    )
    trade = _latest_trade(trades, target_date=target_date)
    if trade is None:
        return {
            "status": "no_trade",
            "target_date": target_date,
            "r2_key": r2_key,
            "content_sha256": digest,
            "retryable": True,
        }

    metadata = {
        "feed": "DELAYED_PUBLIC_TRADE_FILE",
        "feed_mode": "WORKFLOW_R2_RECOVERY",
        "file_type": FILE_TYPE,
        "time_selection": FULL_DAY_SELECTION,
        "trading_location": TRADING_LOCATION,
        "isin": OTEC_ISIN,
        "venue": trade.venue,
        "venue_of_publication": trade.venue_of_publication,
        "trade_unique_identifier": trade.trade_unique_identifier,
        "publication_datetime": trade.publication_datetime,
        "price_semantics": "LATEST_REPORTED_TRADE_NOT_OFFICIAL_CLOSE",
        "payload_policy": "SINGLE_BUFFER_28MIB_R2_ARCHIVED_STREAMED_CSV_MEMBER",
        "r2_key": r2_key,
        "content_sha256": digest,
    }
    document_id = await repository.create_source_document(
        source_code="EURONEXT",
        external_id=f"otec-workflow-recovery:{target_date}",
        document_type="DELAYED_MARKET_DATA_FILE",
        title=f"Euronext full trading-day recovery - OTEC {target_date}",
        url=url,
        published_at=trade.publication_datetime,
        content_sha256=digest,
        metadata=metadata,
    )
    price_id = await repository.upsert_market_price(
        symbol=OTEC_SYMBOL,
        observed_at=trade.trading_datetime,
        trading_date=trade.trading_date,
        price_type="LAST",
        price=format(trade.price, "f"),
        currency=trade.currency,
        source_code="EURONEXT",
        source_document_id=document_id,
        quality="DIRECT",
        metadata=metadata,
    )
    return {
        "status": "ok",
        "target_date": target_date,
        "trading_date": trade.trading_date,
        "trading_datetime": trade.trading_datetime,
        "publication_datetime": trade.publication_datetime,
        "price_nok": format(trade.price, "f"),
        "price_id": price_id,
        "source_document_id": document_id,
        "r2_key": r2_key,
        "content_sha256": digest,
    }


async def ensure_otec_eod(
    repository,
    archive_bucket,
    *,
    target_date: str,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> dict[str, Any]:
    """Use existing rolling coverage first, then escalate to the R2 recovery path."""
    target = date.fromisoformat(target_date)
    if not is_oslo_bors_trading_day(target):
        return {"status": "skipped", "reason": "not_trading_day", "target_date": target_date}
    if await eod_otec_check_done(repository, target_date):
        return {
            "status": "skipped",
            "reason": "eod_already_finalized",
            "target_date": target_date,
            "recovery_used": False,
        }

    covered = await finalize_otec_eod_from_coverage(
        repository,
        target_date=target_date,
        current_refresh={
            "status": "ok",
            "selected": "WORKFLOW_EXISTING_COVERAGE",
            "gap_recovery": False,
        },
    )
    if covered.get("status") == "ok":
        return {"recovery_used": False, "coverage_result": covered, **covered}

    recovered = await recover_otec_to_r2(
        repository,
        archive_bucket,
        target_date=target_date,
        fetcher=fetcher,
    )
    if recovered.get("status") != "ok":
        return {"recovery_used": True, "coverage_result": covered, **recovered}

    finalized = await finalize_otec_eod_from_coverage(
        repository,
        target_date=target_date,
        current_refresh={
            "status": "ok",
            "selected": FULL_DAY_SELECTION,
            "gap_recovery": True,
        },
    )
    return {
        "status": finalized.get("status", "ok"),
        "target_date": target_date,
        "recovery_used": True,
        "recovery": recovered,
        "finalization": finalized,
    }

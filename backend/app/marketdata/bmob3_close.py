from __future__ import annotations

import hashlib
from datetime import date
from typing import Any

from app.db.connection import get_connection
from app.db.repository import create_source_document, upsert_market_price
from app.marketdata.b3_calendar import is_b3_trading_day, previous_b3_trading_day
from app.marketdata.b3_cotahist import B3_DAILY_URL, download_cotahist_day, parse_cotahist_zip_bytes

BMOB3_SYMBOL = "BMOB3"


def _existing_b3_close(database_path: str | None, trading_date: str) -> bool:
    with get_connection(database_path) as connection:
        row = connection.execute(
            """
            SELECT 1
            FROM market_prices mp
            JOIN instruments i ON i.id=mp.instrument_id
            JOIN sources s ON s.id=mp.source_id
            WHERE i.symbol='BMOB3'
              AND mp.trading_date=?
              AND mp.price_type='CLOSE'
              AND s.code='B3'
            LIMIT 1
            """,
            (trading_date,),
        ).fetchone()
    return row is not None


def import_bmob3_daily_close_payload(
    payload: bytes,
    *,
    trading_day: date,
    database_path: str | None = None,
) -> dict[str, Any]:
    rows = parse_cotahist_zip_bytes(payload, BMOB3_SYMBOL)
    matching = [row for row in rows if row.trading_date == trading_day.isoformat()]
    if len(matching) != 1:
        raise ValueError(
            f"Forventet én BMOB3-rad i daglig COTAHIST for {trading_day.isoformat()}, fant {len(matching)}"
        )
    item = matching[0]
    digest = hashlib.sha256(payload).hexdigest()
    url = B3_DAILY_URL.format(date_ddmmyyyy=trading_day.strftime("%d%m%Y"))
    metadata = {
        "ticker": BMOB3_SYMBOL,
        "format": "COTAHIST_DAILY",
        "trading_date": trading_day.isoformat(),
        "trades": item.trades,
        "volume_brl": str(item.volume),
        "isin": item.isin,
        "price_semantics": "OFFICIAL_DAILY_CLOSE",
    }

    with get_connection(database_path) as connection:
        document_id = create_source_document(
            connection,
            source_code="B3",
            external_id=f"cotahist-daily-{trading_day.isoformat()}-{digest[:16]}",
            document_type="MARKET_DATA_FILE",
            title=f"B3 daily COTAHIST {trading_day.isoformat()} - BMOB3",
            url=url,
            content_sha256=digest,
            metadata=metadata,
        )
        price_id = upsert_market_price(
            connection,
            symbol=BMOB3_SYMBOL,
            observed_at=f"{trading_day.isoformat()}T23:59:59Z",
            trading_date=trading_day.isoformat(),
            price_type="CLOSE",
            price=item.close,
            currency="BRL",
            source_code="B3",
            source_document_id=document_id,
            quality="DIRECT",
            metadata=metadata,
        )
        connection.commit()

    return {
        "status": "ok",
        "trading_date": trading_day.isoformat(),
        "price_type": "CLOSE",
        "quality": "DIRECT",
        "price_brl": str(item.close),
        "price_id": price_id,
        "source_url": url,
        "zip_bytes": len(payload),
    }


def refresh_bmob3_official_close(
    database_path: str | None = None,
    *,
    target_date: str | None = None,
) -> dict[str, Any]:
    """Import the newest published official BMOB3 daily CLOSE without the annual ZIP.

    On a live trading day B3's file for today is normally unavailable until the session
    has been processed, so the current date is tried first and the previous B3 trading
    day is the safe fallback. Existing B3 CLOSE rows are not downloaded again.
    """
    target_day = date.fromisoformat(target_date) if target_date else date.today()
    candidates: list[date]
    if is_b3_trading_day(target_day):
        candidates = [target_day, previous_b3_trading_day(target_day)]
    else:
        candidates = [previous_b3_trading_day(target_day)]

    attempted: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate_iso = candidate.isoformat()
        if _existing_b3_close(database_path, candidate_iso):
            return {
                "status": "skipped",
                "reason": "official_close_already_present",
                "trading_date": candidate_iso,
                "attempted": attempted,
            }
        payload = download_cotahist_day(candidate)
        attempted.append(
            {
                "trading_date": candidate_iso,
                "available": payload is not None,
            }
        )
        if payload is None:
            continue
        result = import_bmob3_daily_close_payload(
            payload,
            trading_day=candidate,
            database_path=database_path,
        )
        result["attempted"] = attempted
        return result

    return {
        "status": "unavailable",
        "reason": "daily_cotahist_not_published",
        "attempted": attempted,
    }

from __future__ import annotations

import hashlib
import json
from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from app.db.connection import get_connection
from app.db.repository import create_source_document, upsert_market_price
from app.marketdata.euronext_delayed import (
    OTEC_SYMBOL,
    DelayedTrade,
    download_euronext_delayed_equities,
    parse_euronext_delayed_trades,
    refresh_otec_delayed_price,
)
from app.marketdata.oslo_calendar import is_oslo_bors_trading_day

OSLO_TZ = ZoneInfo("Europe/Oslo")
# Euronext delayed post-trade data is available with max 15-minute delay. With the
# production scheduler running every 30 minutes, LAST_HOUR is a safety overlap so a
# thinly traded OTEC print cannot fall into a polling gap after LAST_15_MINUTES returns
# no OTEC row.
INTRADAY_SELECTIONS = ("LAST_15_MINUTES", "LAST_HOUR")
# Normal Oslo equity trading is finished well before this. Waiting until 16:45 also
# leaves room for Euronext's delayed publication window before taking the one daily
# CURRENT_TRADING_DAY snapshot.
EOD_FINALIZE_AFTER = time(16, 45)


def refresh_otec_intraday_price(
    database_path: str | None = None,
    *,
    timeout: int = 45,
) -> dict[str, Any]:
    """Refresh OTEC from small delayed windows instead of the full trading-day file."""
    result = refresh_otec_delayed_price(
        database_path,
        selections=INTRADAY_SELECTIONS,
        timeout=timeout,
    )
    return {"feed_mode": "delayed_intraday", **result}


def _latest_trade_for_date(trades: list[DelayedTrade], target_date: str) -> DelayedTrade | None:
    candidates = [trade for trade in trades if trade.trading_date == target_date]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda item: (
            item.trading_datetime,
            item.publication_datetime,
            item.trade_unique_identifier,
        ),
    )


def eod_otec_check_done(database_path: str | None, target_date: str) -> bool:
    with get_connection(database_path) as connection:
        row = connection.execute(
            """
            SELECT 1
            FROM source_documents sd
            JOIN sources s ON s.id = sd.source_id
            WHERE s.code='EURONEXT' AND sd.external_id=?
            LIMIT 1
            """,
            (f"otec-eod-last-check-{target_date}",),
        ).fetchone()
    return row is not None


def finalize_otec_eod_from_payload(
    payload: bytes,
    *,
    source_url: str,
    target_date: str,
    database_path: str | None = None,
    source_selection: str,
) -> dict[str, Any]:
    """Persist the final OTEC trade for a completed session without calling it CLOSE.

    The free MiFID delayed trade files expose transactions, not Euronext's official
    valuation/closing-price field. The final trade is therefore stored as LAST with
    EOD_LAST_TRADE quality. This keeps the data model honest and allows a future EWS
    closPx source to outrank it simply by writing a same-day CLOSE row.
    """
    trades = parse_euronext_delayed_trades(payload)
    latest = _latest_trade_for_date(trades, target_date)
    digest = hashlib.sha256(payload).hexdigest()
    metadata: dict[str, Any] = {
        "feed": "DELAYED_PUBLIC_TRADE_FILE",
        "feed_mode": "EOD_LAST_TRADE",
        "time_selection": source_selection,
        "target_date": target_date,
        "trade_rows_for_otec": sum(trade.trading_date == target_date for trade in trades),
        "price_semantics": "FINAL_REPORTED_TRADE_NOT_OFFICIAL_CLOSE",
        "official_close_upgrade": "EWS prevInstrSess.closPx requires Euronext authKey",
    }

    with get_connection(database_path) as connection:
        document_id = create_source_document(
            connection,
            source_code="EURONEXT",
            external_id=f"otec-eod-last-check-{target_date}",
            document_type="EOD_MARKET_DATA_CHECK",
            title=f"OTEC Euronext delayed EOD last-trade check {target_date}",
            url=source_url,
            published_at=latest.publication_datetime if latest is not None else None,
            content_sha256=digest,
            metadata={**metadata, "found": latest is not None},
        )
        if latest is None:
            connection.commit()
            return {
                "status": "no_trade",
                "feed_mode": "eod_last_trade",
                "target_date": target_date,
                "price_type": None,
                "quality": None,
                "source_url": source_url,
            }

        price_id = upsert_market_price(
            connection,
            symbol=OTEC_SYMBOL,
            observed_at=latest.trading_datetime,
            trading_date=latest.trading_date,
            price_type="LAST",
            price=latest.price,
            currency=latest.currency,
            source_code="EURONEXT",
            source_document_id=document_id,
            quality="EOD_LAST_TRADE",
            metadata={
                **metadata,
                "trade_unique_identifier": latest.trade_unique_identifier,
                "publication_datetime": latest.publication_datetime,
                "venue": latest.venue,
            },
        )
        connection.commit()

    return {
        "status": "ok",
        "feed_mode": "eod_last_trade",
        "target_date": target_date,
        "price_id": price_id,
        "price_type": "LAST",
        "quality": "EOD_LAST_TRADE",
        "price_nok": str(latest.price),
        "trading_datetime": latest.trading_datetime,
        "publication_datetime": latest.publication_datetime,
        "source_url": source_url,
    }


def finalize_otec_eod_price(
    database_path: str | None = None,
    *,
    target_date: str,
    timeout: int = 120,
) -> dict[str, Any]:
    """Fetch the full current-day file once after close and persist its final OTEC trade."""
    if eod_otec_check_done(database_path, target_date):
        return {
            "status": "skipped",
            "reason": "eod_already_finalized",
            "target_date": target_date,
        }
    url, payload = download_euronext_delayed_equities(
        "CURRENT_TRADING_DAY",
        timeout=timeout,
    )
    return finalize_otec_eod_from_payload(
        payload,
        source_url=url,
        target_date=target_date,
        database_path=database_path,
        source_selection="CURRENT_TRADING_DAY",
    )


def maybe_finalize_otec_eod(
    database_path: str | None = None,
    *,
    target_date: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Run the one heavy OTEC day-file request only once and only after the session."""
    current = now or datetime.now(OSLO_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=OSLO_TZ)
    current = current.astimezone(OSLO_TZ)
    target_day = datetime.fromisoformat(target_date).date()

    if target_day != current.date():
        return {"status": "skipped", "reason": "not_current_date", "target_date": target_date}
    if not is_oslo_bors_trading_day(target_day):
        return {"status": "skipped", "reason": "not_trading_day", "target_date": target_date}
    if current.time().replace(tzinfo=None) < EOD_FINALIZE_AFTER:
        return {"status": "skipped", "reason": "before_eod_cutoff", "target_date": target_date}
    return finalize_otec_eod_price(database_path, target_date=target_date)

from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.db.connection import get_connection
from app.db.repository import create_source_document, decimal_text, instrument_id, source_id
from app.marketdata.euronext_delayed import parse_euronext_delayed_trades

ACTIVITY_SEED_PATH = Path(__file__).with_name("data") / "otec_euronext_daily_activity_2024_2026.csv"
EURONEXT_HISTORY_URL = "https://live.euronext.com/en/product/equities/NO0010040611-XOSL"


def _upsert_activity(
    connection,
    *,
    trading_date: str,
    volume_shares: int,
    last_price_nok: Decimal | str | None,
    source_document_id: int,
    quality: str,
    metadata: dict[str, Any],
) -> None:
    iid = instrument_id(connection, "OTEC")
    sid = source_id(connection, "EURONEXT")
    connection.execute(
        """
        INSERT INTO market_activity(
            instrument_id, trading_date, volume_shares, last_price_nok,
            source_id, source_document_id, quality, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(instrument_id, trading_date, source_id) DO UPDATE SET
            volume_shares=excluded.volume_shares,
            last_price_nok=COALESCE(excluded.last_price_nok, market_activity.last_price_nok),
            source_document_id=excluded.source_document_id,
            quality=CASE
                WHEN market_activity.quality='HISTORICAL_EXPORT' THEN market_activity.quality
                ELSE excluded.quality
            END,
            metadata_json=CASE
                WHEN market_activity.quality='HISTORICAL_EXPORT' THEN market_activity.metadata_json
                ELSE excluded.metadata_json
            END,
            updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
        """,
        (
            iid,
            trading_date,
            int(volume_shares),
            decimal_text(last_price_nok) if last_price_nok is not None else None,
            sid,
            source_document_id,
            quality,
            json.dumps(metadata, ensure_ascii=False, sort_keys=True),
        ),
    )


def seed_otec_activity_history(database_path: str | None = None) -> dict[str, Any]:
    """Seed compact daily OTEC volume history derived from the official Euronext export.

    The repository stores only date, close and Number of Shares, not the original export.
    This gives the forecast a deterministic historical volume baseline while preserving
    explicit provenance to the official Euronext source.
    """
    raw = ACTIVITY_SEED_PATH.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    rows: list[dict[str, str]] = []
    with ACTIVITY_SEED_PATH.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("OTEC Euronext activity seed is empty")

    written = 0
    with get_connection(database_path) as connection:
        document_id = create_source_document(
            connection,
            source_code="EURONEXT",
            external_id=f"otec-daily-activity-derived-{digest[:20]}",
            document_type="MARKET_DATA_DERIVED_FILE",
            title="OTEC daily activity derived from Euronext historical export",
            url=EURONEXT_HISTORY_URL,
            content_sha256=digest,
            metadata={
                "symbol": "OTEC",
                "fields": ["date", "close_nok", "volume_shares"],
                "volume_source_field": "Number of Shares",
                "derived_compact_copy": True,
                "source_quality": "OFFICIAL_EXCHANGE_EXPORT",
            },
        )
        for row in rows:
            trading_date = date.fromisoformat(row["date"]).isoformat()
            volume = int(row["volume_shares"])
            if volume < 0:
                raise ValueError(f"Negative OTEC volume in activity seed: {trading_date}")
            _upsert_activity(
                connection,
                trading_date=trading_date,
                volume_shares=volume,
                last_price_nok=Decimal(row["close_nok"]),
                source_document_id=document_id,
                quality="HISTORICAL_EXPORT",
                metadata={"source_field": "Number of Shares"},
            )
            written += 1
        connection.commit()

    return {
        "rows": written,
        "from": rows[0]["date"],
        "to": rows[-1]["date"],
        "sha256": digest,
    }


def ingest_previous_trading_day_activity(
    payload: bytes,
    *,
    source_url: str,
    database_path: str | None = None,
    check_date: str | None = None,
) -> dict[str, Any]:
    """Aggregate official delayed-trade rows into one finalized prior-day OTEC volume.

    This is only intended for Euronext PREVIOUS_TRADING_DAY payloads. It must not be
    used for CURRENT_TRADING_DAY because that file is incomplete while the market is open.
    """
    trades = parse_euronext_delayed_trades(payload)
    today_key = check_date or date.today().isoformat()
    digest = hashlib.sha256(payload).hexdigest()

    by_date: dict[str, list] = defaultdict(list)
    for trade in trades:
        by_date[trade.trading_date].append(trade)

    with get_connection(database_path) as connection:
        document_id = create_source_document(
            connection,
            source_code="EURONEXT",
            external_id=f"otec-activity-previous-day-check-{today_key}",
            document_type="DELAYED_MARKET_ACTIVITY_FILE",
            title="Euronext previous trading day OTEC activity",
            url=source_url,
            content_sha256=digest,
            metadata={
                "time_selection": "PREVIOUS_TRADING_DAY",
                "aggregation": "sum MifidQuantity for exact OTEC/XOSL/MONE/NOK trades",
                "source_quality": "OFFICIAL_DELAYED_TRADE_FILE",
            },
        )
        written = 0
        dates: list[str] = []
        for trading_date, day_trades in sorted(by_date.items()):
            latest = max(day_trades, key=lambda item: (item.trading_datetime, item.publication_datetime))
            quantity = sum((item.quantity for item in day_trades), Decimal("0"))
            if quantity != quantity.to_integral_value():
                raise ValueError(f"Non-integer OTEC share volume from Euronext: {quantity}")
            _upsert_activity(
                connection,
                trading_date=trading_date,
                volume_shares=int(quantity),
                last_price_nok=latest.price,
                source_document_id=document_id,
                quality="DELAYED_TRADE_SUM",
                metadata={
                    "trade_rows": len(day_trades),
                    "latest_trade_at": latest.trading_datetime,
                    "latest_trade_price_nok": decimal_text(latest.price),
                },
            )
            written += 1
            dates.append(trading_date)
        connection.commit()

    return {
        "status": "ok" if written else "no_trade",
        "written": written,
        "dates": dates,
        "trade_rows": len(trades),
    }


def activity_check_done(database_path: str | None = None, *, check_date: str | None = None) -> bool:
    day = check_date or date.today().isoformat()
    with get_connection(database_path) as connection:
        row = connection.execute(
            """
            SELECT 1
            FROM source_documents sd JOIN sources s ON s.id=sd.source_id
            WHERE s.code='EURONEXT' AND sd.external_id=? LIMIT 1
            """,
            (f"otec-activity-previous-day-check-{day}",),
        ).fetchone()
    return row is not None


def market_activity_status(database_path: str | None = None) -> dict[str, Any]:
    with get_connection(database_path) as connection:
        row = connection.execute(
            """
            SELECT COUNT(*) n, MIN(trading_date) min_date, MAX(trading_date) max_date,
                   SUM(CASE WHEN volume_shares > 0 THEN 1 ELSE 0 END) positive_days
            FROM market_activity ma JOIN instruments i ON i.id=ma.instrument_id
            WHERE i.symbol='OTEC'
            """
        ).fetchone()
    return {
        "status": "ok" if row["n"] else "empty",
        "count": int(row["n"] or 0),
        "positive_days": int(row["positive_days"] or 0),
        "from": row["min_date"],
        "to": row["max_date"],
    }

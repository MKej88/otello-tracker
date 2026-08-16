from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from app.db.connection import get_connection
from app.db.repository import create_source_document, upsert_fx_rate, upsert_market_price
from app.marketdata.b3_cotahist import B3_YEARLY_URL, parse_cotahist_zip_bytes
from app.marketdata.ecb_fx import derive_nok_cross_rates, parse_ecb_csv
from app.marketdata.euronext_csv import parse_euronext_historical_csv

OTEC_EURONEXT_HISTORY_URL = (
    "https://live.euronext.com/en/popout-page/getHistoricalPrice/NO0010040611-XOSL"
)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def import_b3_bmob3_zip(payload: bytes, *, year: int, database_path: str | None = None) -> int:
    prices = parse_cotahist_zip_bytes(payload, "BMOB3")
    digest = _sha256(payload)
    written = 0
    with get_connection(database_path) as connection:
        document_id = create_source_document(
            connection,
            source_code="B3",
            external_id=f"cotahist-{year}-{digest[:16]}",
            document_type="MARKET_DATA_FILE",
            title=f"B3 COTAHIST {year} - BMOB3 source file",
            url=B3_YEARLY_URL.format(year=year),
            content_sha256=digest,
            metadata={"year": year, "ticker": "BMOB3", "format": "COTAHIST"},
        )
        for item in prices:
            upsert_market_price(
                connection,
                symbol="BMOB3",
                observed_at=f"{item.trading_date}T23:59:59Z",
                trading_date=item.trading_date,
                price_type="CLOSE",
                price=item.close,
                currency="BRL",
                source_code="B3",
                source_document_id=document_id,
            )
            written += 1
        connection.commit()
    return written


def import_b3_bmob3_file(path: str | Path, *, year: int, database_path: str | None = None) -> int:
    return import_b3_bmob3_zip(Path(path).read_bytes(), year=year, database_path=database_path)


def import_ecb_fx_csv(
    text: str,
    *,
    source_url: str,
    database_path: str | None = None,
) -> int:
    payload = text.encode("utf-8")
    rows = derive_nok_cross_rates(parse_ecb_csv(text))
    digest = _sha256(payload)
    written = 0
    with get_connection(database_path) as connection:
        document_id = create_source_document(
            connection,
            source_code="ECB",
            external_id=f"exr-cross-{digest[:20]}",
            document_type="API_RESPONSE",
            title="ECB daily reference rates used for BRL/NOK and USD/NOK",
            url=source_url,
            content_sha256=digest,
            metadata={"derived_pairs": ["BRL/NOK", "USD/NOK"], "method": "EUR cross"},
        )
        for item in rows:
            upsert_fx_rate(
                connection,
                base_currency=item.base_currency,
                quote_currency=item.quote_currency,
                observed_at=f"{item.trading_date}T00:00:00Z",
                rate=item.rate,
                source_code="ECB",
                source_document_id=document_id,
            )
            written += 1
        connection.commit()
    return written


def import_euronext_otec_csv(
    text: str,
    *,
    date_order: str = "DMY",
    database_path: str | None = None,
) -> int:
    payload = text.encode("utf-8")
    prices = parse_euronext_historical_csv(text, date_order=date_order)
    digest = _sha256(payload)
    written = 0
    with get_connection(database_path) as connection:
        document_id = create_source_document(
            connection,
            source_code="EURONEXT",
            external_id=f"otec-history-{digest[:20]}",
            document_type="MARKET_DATA_FILE",
            title="Euronext Live historical prices - OTEC",
            url=OTEC_EURONEXT_HISTORY_URL,
            content_sha256=digest,
            metadata={"symbol": "OTEC", "format": "CSV", "date_order": date_order},
        )
        for item in prices:
            upsert_market_price(
                connection,
                symbol="OTEC",
                observed_at=f"{item.trading_date}T23:59:59Z",
                trading_date=item.trading_date,
                price_type="CLOSE",
                price=item.close,
                currency="NOK",
                source_code="EURONEXT",
                source_document_id=document_id,
            )
            written += 1
        connection.commit()
    return written


def _coverage(connection, symbol: str) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT COUNT(*) AS n, MIN(mp.trading_date) AS min_date, MAX(mp.trading_date) AS max_date
        FROM market_prices mp
        JOIN instruments i ON i.id = mp.instrument_id
        WHERE i.symbol = ? AND mp.price_type = 'CLOSE'
        """,
        (symbol,),
    ).fetchone()
    return {"count": row["n"], "from": row["min_date"], "to": row["max_date"]}


def _fx_coverage(connection, base: str) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT COUNT(*) AS n,
               MIN(substr(observed_at, 1, 10)) AS min_date,
               MAX(substr(observed_at, 1, 10)) AS max_date
        FROM fx_rates
        WHERE base_currency = ? AND quote_currency = 'NOK'
        """,
        (base,),
    ).fetchone()
    return {"count": row["n"], "from": row["min_date"], "to": row["max_date"]}


def market_data_status(database_path: str | None = None) -> dict[str, Any]:
    with get_connection(database_path) as connection:
        return {
            "status": "ok",
            "BMOB3": _coverage(connection, "BMOB3"),
            "OTEC": _coverage(connection, "OTEC"),
            "BRL_NOK": _fx_coverage(connection, "BRL"),
            "USD_NOK": _fx_coverage(connection, "USD"),
        }

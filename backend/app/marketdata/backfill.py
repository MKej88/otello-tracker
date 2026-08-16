from __future__ import annotations

import hashlib
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.db.connection import get_connection
from app.db.repository import create_source_document, upsert_fx_rate, upsert_market_price
from app.marketdata.b3_cotahist import B3_YEARLY_URL, parse_cotahist_zip_bytes
from app.marketdata.ecb_fx import derive_nok_cross_rates, parse_ecb_csv
from app.marketdata.euronext_csv import parse_euronext_historical_csv
from app.marketdata.investing_csv import (
    parse_investing_historical_csv,
    reconstruct_otec_2022_distribution,
)

OTEC_EURONEXT_HISTORY_URL = (
    "https://live.euronext.com/en/popout-page/getHistoricalPrice/NO0010040611-XOSL"
)
OTEC_INVESTING_HISTORY_URL = (
    "https://www.investing.com/equities/opera-software-asa-historical-data"
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
                quality="DIRECT",
            )
            written += 1
        connection.commit()
    return written


def import_investing_otec_csv(
    text: str,
    *,
    database_path: str | None = None,
    overlap_tolerance: Decimal = Decimal("0.001"),
) -> dict[str, Any]:
    """Import a manual Investing.com CSV export as a free OTEC history backfill.

    The exported series is backward-adjusted for Otello's NOK 21 distribution before
    2022-08-09. That segment is reconstructed and explicitly tagged RECONSTRUCTED.
    Dates on/after the ex-date are stored as DIRECT. If official Euronext rows already
    exist, every overlapping direct close is validated before the transaction commits.
    """
    payload = text.encode("utf-8")
    raw_rows = parse_investing_historical_csv(text)
    prices, adjustment = reconstruct_otec_2022_distribution(raw_rows)
    digest = _sha256(payload)

    written = 0
    overlap_checked = 0
    with get_connection(database_path) as connection:
        official_rows = {
            row["trading_date"]: Decimal(row["price"])
            for row in connection.execute(
                """
                SELECT mp.trading_date, mp.price
                FROM market_prices mp
                JOIN instruments i ON i.id = mp.instrument_id
                JOIN sources s ON s.id = mp.source_id
                WHERE i.symbol = 'OTEC' AND mp.price_type = 'CLOSE'
                  AND s.code = 'EURONEXT'
                """
            )
        }

        for item in prices:
            official = official_rows.get(item.trading_date)
            if official is not None and item.quality == "DIRECT":
                overlap_checked += 1
                if abs(official - item.close) > overlap_tolerance:
                    raise ValueError(
                        "Investing/Euronext avvik på "
                        f"{item.trading_date}: Investing={item.close}, Euronext={official}"
                    )

        document_id = create_source_document(
            connection,
            source_code="INVESTING",
            external_id=f"otec-manual-export-{digest[:20]}",
            document_type="MARKET_DATA_FILE",
            title="Investing.com manual historical price export - OTEC",
            url=OTEC_INVESTING_HISTORY_URL,
            content_sha256=digest,
            metadata={
                "symbol": "OTEC",
                "format": "CSV",
                "manual_export": True,
                "automated_scraping": False,
                "distribution_reconstruction": {
                    "ex_date": adjustment.ex_date,
                    "dividend_nok": str(adjustment.dividend_nok),
                    "last_including_date": adjustment.last_including_date,
                    "adjusted_close_last_including": str(adjustment.adjusted_close_last_including),
                    "reconstructed_close_last_including": str(adjustment.reconstructed_close_last_including),
                    "backward_adjustment_factor": str(adjustment.backward_adjustment_factor),
                    "reconstruction_multiplier": str(adjustment.reconstruction_multiplier),
                },
                "official_overlap_rows_checked": overlap_checked,
                "official_overlap_tolerance_nok": str(overlap_tolerance),
            },
        )

        reconstructed = 0
        direct = 0
        for item in prices:
            if item.quality == "RECONSTRUCTED":
                reconstructed += 1
            else:
                direct += 1
            upsert_market_price(
                connection,
                symbol="OTEC",
                observed_at=f"{item.trading_date}T23:59:59Z",
                trading_date=item.trading_date,
                price_type="CLOSE",
                price=item.close,
                currency="NOK",
                source_code="INVESTING",
                source_document_id=document_id,
                quality=item.quality,
                metadata={
                    "source_close": str(item.source_close),
                    "distribution_adjustment_factor": (
                        str(item.adjustment_factor) if item.adjustment_factor is not None else None
                    ),
                },
            )
            written += 1
        connection.commit()

    return {
        "rows_written": written,
        "direct_rows": direct,
        "reconstructed_rows": reconstructed,
        "from": prices[0].trading_date,
        "to": prices[-1].trading_date,
        "euronext_overlap_checked": overlap_checked,
        "reconstruction_multiplier": str(adjustment.reconstruction_multiplier),
    }


def _coverage(connection, symbol: str) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT COUNT(*) AS rows_total,
               COUNT(DISTINCT mp.trading_date) AS n,
               MIN(mp.trading_date) AS min_date,
               MAX(mp.trading_date) AS max_date,
               COUNT(DISTINCT CASE WHEN mp.quality = 'DIRECT' THEN mp.trading_date END) AS direct_dates,
               COUNT(DISTINCT CASE WHEN mp.quality = 'RECONSTRUCTED' THEN mp.trading_date END) AS reconstructed_dates
        FROM market_prices mp
        JOIN instruments i ON i.id = mp.instrument_id
        WHERE i.symbol = ? AND mp.price_type = 'CLOSE'
        """,
        (symbol,),
    ).fetchone()
    return {
        "count": row["n"],
        "rows_total": row["rows_total"],
        "from": row["min_date"],
        "to": row["max_date"],
        "direct_dates": row["direct_dates"],
        "reconstructed_dates": row["reconstructed_dates"],
    }


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

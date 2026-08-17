from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime, time as dt_time
from decimal import Decimal, InvalidOperation
from http.client import IncompleteRead
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from app.db.connection import get_connection
from app.db.repository import create_source_document, upsert_market_price
from app.marketdata.b3_calendar import is_ash_wednesday, is_b3_trading_day

BMOB3_SYMBOL = "BMOB3"
B3_TZ = ZoneInfo("America/Sao_Paulo")
B3_QUOTE_URL = "https://cotacao.b3.com.br/mds/api/v1/instrumentQuotation/BMOB3"
# The public B3 website states that displayed equity market data is delayed by 15 minutes.
# This lightweight endpoint is B3-hosted but is not part of the documented B2B API catalog,
# so the adapter deliberately treats it as a public web quote rather than a contractual API.
INTRADAY_START = dt_time(10, 15)
ASH_WEDNESDAY_START = dt_time(13, 15)
# B3's current equity timetable includes after-market trading and permits corrections later.
# Waiting until 19:15 Sao Paulo time also gives the public delayed quote time to settle.
EOD_FINALIZE_AFTER = dt_time(19, 15)


@dataclass(frozen=True)
class Bmob3WebQuote:
    symbol: str
    price: Decimal
    provider_datetime: datetime
    open_price: Decimal | None
    min_price: Decimal | None
    max_price: Decimal | None
    average_price: Decimal | None
    price_change_pct: Decimal | None
    total_trades: int | None
    description: str | None
    market_name: str | None
    raw: dict[str, Any]

    @property
    def trading_date(self) -> str:
        return self.provider_datetime.astimezone(B3_TZ).date().isoformat()

    @property
    def observed_at(self) -> str:
        return self.provider_datetime.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def parse_bmob3_web_quote(payload: bytes | str) -> Bmob3WebQuote:
    if isinstance(payload, bytes):
        text = payload.decode("utf-8-sig")
    else:
        text = payload
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("B3 quote response is not an object")
    if ((data.get("BizSts") or {}).get("cd")) != "OK":
        raise ValueError(f"B3 quote status is not OK: {data.get('BizSts')!r}")

    timestamp = ((data.get("Msg") or {}).get("dtTm"))
    if not timestamp:
        raise ValueError("B3 quote response is missing Msg.dtTm")
    provider_datetime = datetime.strptime(str(timestamp), "%Y-%m-%d %H:%M:%S").replace(tzinfo=B3_TZ)

    selected: dict[str, Any] | None = None
    for item in data.get("Trad") or []:
        security = item.get("scty") or {}
        if str(security.get("symb") or "").upper() == BMOB3_SYMBOL:
            selected = item
            break
    if selected is None:
        raise ValueError("B3 quote response did not contain BMOB3")

    security = selected.get("scty") or {}
    quotation = security.get("SctyQtn") or {}
    price = _decimal(quotation.get("curPrc"))
    if price is None or price <= 0:
        raise ValueError(f"B3 BMOB3 curPrc is invalid: {quotation.get('curPrc')!r}")

    total_trades = selected.get("ttlQty")
    try:
        total_trades = int(total_trades) if total_trades is not None else None
    except (TypeError, ValueError):
        total_trades = None

    return Bmob3WebQuote(
        symbol=BMOB3_SYMBOL,
        price=price,
        provider_datetime=provider_datetime,
        open_price=_decimal(quotation.get("opngPric")),
        min_price=_decimal(quotation.get("minPric")),
        max_price=_decimal(quotation.get("maxPric")),
        average_price=_decimal(quotation.get("avrgPric")),
        price_change_pct=_decimal(quotation.get("prcFlcn")),
        total_trades=total_trades,
        description=str(security.get("desc")) if security.get("desc") is not None else None,
        market_name=str((security.get("mkt") or {}).get("nm")) if (security.get("mkt") or {}).get("nm") is not None else None,
        raw=data,
    )


def download_bmob3_web_quote(timeout: int = 20, attempts: int = 3) -> tuple[str, bytes]:
    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        request = Request(
            B3_QUOTE_URL,
            headers={
                "User-Agent": "Mozilla/5.0 otello-tracker/0.4 (+private research)",
                "Accept": "application/json",
                "Connection": "close",
            },
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                payload = response.read()
            if not payload.lstrip().startswith(b"{"):
                raise RuntimeError("B3 quote endpoint did not return JSON")
            return B3_QUOTE_URL, payload
        except (IncompleteRead, HTTPError, URLError, TimeoutError, OSError, RuntimeError) as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(min(2 ** (attempt - 1), 4))
    raise RuntimeError(f"B3 BMOB3 quote failed after {attempts} attempts") from last_error


def _quote_metadata(quote: Bmob3WebQuote, *, feed_mode: str) -> dict[str, Any]:
    return {
        "feed": "B3_PUBLIC_WEB_QUOTE",
        "feed_mode": feed_mode,
        "price_semantics": "DELAYED_CURRENT_PRICE_NOT_COTAHIST_CLOSE",
        "provider_timestamp_sao_paulo": quote.provider_datetime.isoformat(),
        "open_price": str(quote.open_price) if quote.open_price is not None else None,
        "min_price": str(quote.min_price) if quote.min_price is not None else None,
        "max_price": str(quote.max_price) if quote.max_price is not None else None,
        "average_price": str(quote.average_price) if quote.average_price is not None else None,
        "price_change_pct": str(quote.price_change_pct) if quote.price_change_pct is not None else None,
        "total_trades": quote.total_trades,
        "description": quote.description,
        "market_name": quote.market_name,
        "official_close_upgrade": "B3 COTAHIST CLOSE outranks same-day LAST when available",
    }


def _persist_intraday_quote(
    quote: Bmob3WebQuote,
    payload: bytes,
    *,
    source_url: str,
    database_path: str | None,
) -> int:
    digest = hashlib.sha256(payload).hexdigest()
    with get_connection(database_path) as connection:
        document_id = create_source_document(
            connection,
            source_code="B3",
            external_id=f"bmob3-web-quote-{digest[:20]}",
            document_type="API_RESPONSE",
            title=f"B3 public BMOB3 delayed web quote {quote.observed_at}",
            url=source_url,
            published_at=quote.observed_at,
            content_sha256=digest,
            metadata=_quote_metadata(quote, feed_mode="DELAYED_INTRADAY"),
        )
        price_id = upsert_market_price(
            connection,
            symbol=BMOB3_SYMBOL,
            observed_at=quote.observed_at,
            trading_date=quote.trading_date,
            price_type="LAST",
            price=quote.price,
            currency="BRL",
            source_code="B3",
            source_document_id=document_id,
            quality="DIRECT",
            metadata=_quote_metadata(quote, feed_mode="DELAYED_INTRADAY"),
        )
        connection.commit()
    return price_id


def refresh_bmob3_intraday_price(
    database_path: str | None = None,
    *,
    now: datetime | None = None,
    timeout: int = 20,
) -> dict[str, Any]:
    current = now or datetime.now(B3_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=B3_TZ)
    current = current.astimezone(B3_TZ)
    day = current.date()

    if not is_b3_trading_day(day):
        return {"status": "skipped", "reason": "not_b3_trading_day", "target_date": day.isoformat()}
    start = ASH_WEDNESDAY_START if is_ash_wednesday(day) else INTRADAY_START
    if current.time().replace(tzinfo=None) < start:
        return {"status": "skipped", "reason": "before_b3_quote_window", "target_date": day.isoformat()}
    if current.time().replace(tzinfo=None) >= EOD_FINALIZE_AFTER:
        return {"status": "skipped", "reason": "eod_window_has_priority", "target_date": day.isoformat()}

    url, payload = download_bmob3_web_quote(timeout=timeout)
    quote = parse_bmob3_web_quote(payload)
    if quote.trading_date != day.isoformat():
        return {
            "status": "stale",
            "reason": "provider_date_mismatch",
            "target_date": day.isoformat(),
            "provider_date": quote.trading_date,
        }
    price_id = _persist_intraday_quote(quote, payload, source_url=url, database_path=database_path)
    return {
        "status": "ok",
        "feed_mode": "delayed_intraday",
        "price_id": price_id,
        "price_type": "LAST",
        "quality": "DIRECT",
        "price_brl": str(quote.price),
        "trading_date": quote.trading_date,
        "observed_at": quote.observed_at,
        "source_url": url,
    }


def bmob3_eod_check_done(database_path: str | None, target_date: str) -> bool:
    with get_connection(database_path) as connection:
        row = connection.execute(
            """
            SELECT 1
            FROM source_documents sd
            JOIN sources s ON s.id = sd.source_id
            WHERE s.code='B3' AND sd.external_id=?
            LIMIT 1
            """,
            (f"bmob3-eod-last-check-{target_date}",),
        ).fetchone()
    return row is not None


def finalize_bmob3_eod_price(
    database_path: str | None = None,
    *,
    target_date: str,
    timeout: int = 20,
) -> dict[str, Any]:
    if bmob3_eod_check_done(database_path, target_date):
        return {"status": "skipped", "reason": "eod_already_finalized", "target_date": target_date}

    url, payload = download_bmob3_web_quote(timeout=timeout)
    quote = parse_bmob3_web_quote(payload)
    if quote.trading_date != target_date:
        return {
            "status": "stale",
            "reason": "provider_date_mismatch",
            "target_date": target_date,
            "provider_date": quote.trading_date,
        }

    digest = hashlib.sha256(payload).hexdigest()
    metadata = _quote_metadata(quote, feed_mode="EOD_LAST_QUOTE")
    metadata["price_semantics"] = "FINAL_DELAYED_WEB_QUOTE_NOT_COTAHIST_CLOSE"
    with get_connection(database_path) as connection:
        document_id = create_source_document(
            connection,
            source_code="B3",
            external_id=f"bmob3-eod-last-check-{target_date}",
            document_type="EOD_MARKET_DATA_CHECK",
            title=f"BMOB3 B3 delayed EOD last-quote check {target_date}",
            url=url,
            published_at=quote.observed_at,
            content_sha256=digest,
            metadata=metadata,
        )
        price_id = upsert_market_price(
            connection,
            symbol=BMOB3_SYMBOL,
            observed_at=quote.observed_at,
            trading_date=target_date,
            price_type="LAST",
            price=quote.price,
            currency="BRL",
            source_code="B3",
            source_document_id=document_id,
            quality="DIRECT",
            metadata=metadata,
        )
        connection.commit()

    return {
        "status": "ok",
        "feed_mode": "eod_last_quote",
        "target_date": target_date,
        "price_id": price_id,
        "price_type": "LAST",
        "quality": "DIRECT",
        "price_brl": str(quote.price),
        "observed_at": quote.observed_at,
        "source_url": url,
    }


def maybe_finalize_bmob3_eod(
    database_path: str | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(B3_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=B3_TZ)
    current = current.astimezone(B3_TZ)
    day = current.date()
    target_date = day.isoformat()

    if not is_b3_trading_day(day):
        return {"status": "skipped", "reason": "not_b3_trading_day", "target_date": target_date}
    if current.time().replace(tzinfo=None) < EOD_FINALIZE_AFTER:
        return {"status": "skipped", "reason": "before_b3_eod_cutoff", "target_date": target_date}
    return finalize_bmob3_eod_price(database_path, target_date=target_date)

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, time as dt_time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo

from b3_calendar import is_ash_wednesday, is_b3_trading_day
from repository import D1WriteRepository

BMOB3_SYMBOL = "BMOB3"
B3_TZ = ZoneInfo("America/Sao_Paulo")
B3_QUOTE_URL = "https://cotacao.b3.com.br/mds/api/v1/instrumentQuotation/BMOB3"
B3_PUBLIC_DELAY_MINUTES = 15
MAX_QUOTE_BYTES = 256 * 1024
INTRADAY_START = dt_time(10, 15)
ASH_WEDNESDAY_START = dt_time(13, 15)
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

    @property
    def trading_date(self) -> str:
        return self.provider_datetime.astimezone(B3_TZ).date().isoformat()

    @property
    def provider_at(self) -> str:
        return self.provider_datetime.astimezone(UTC).isoformat().replace("+00:00", "Z")

    @property
    def observed_at(self) -> str:
        effective = self.provider_datetime - timedelta(minutes=B3_PUBLIC_DELAY_MINUTES)
        return effective.astimezone(UTC).isoformat().replace("+00:00", "Z")


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
    if len(text.encode("utf-8")) > MAX_QUOTE_BYTES:
        raise ValueError("B3 quote response overstiger Worker-grensen")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("B3 quote response is not an object")
    if ((data.get("BizSts") or {}).get("cd")) != "OK":
        raise ValueError(f"B3 quote status is not OK: {data.get('BizSts')!r}")

    timestamp = ((data.get("Msg") or {}).get("dtTm"))
    if not timestamp:
        raise ValueError("B3 quote response is missing Msg.dtTm")
    provider_datetime = datetime.strptime(str(timestamp), "%Y-%m-%d %H:%M:%S").replace(
        tzinfo=B3_TZ
    )

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
        market_name=(
            str((security.get("mkt") or {}).get("nm"))
            if (security.get("mkt") or {}).get("nm") is not None
            else None
        ),
    )


def _quote_metadata(quote: Bmob3WebQuote, *, feed_mode: str) -> dict[str, Any]:
    return {
        "feed": "B3_PUBLIC_WEB_QUOTE",
        "feed_mode": feed_mode,
        "price_semantics": "DELAYED_CURRENT_PRICE_NOT_COTAHIST_CLOSE",
        "public_delay_minutes": B3_PUBLIC_DELAY_MINUTES,
        "provider_timestamp_sao_paulo": quote.provider_datetime.isoformat(),
        "provider_timestamp_utc": quote.provider_at,
        "market_data_effective_at": quote.observed_at,
        "open_price": format(quote.open_price, "f") if quote.open_price is not None else None,
        "min_price": format(quote.min_price, "f") if quote.min_price is not None else None,
        "max_price": format(quote.max_price, "f") if quote.max_price is not None else None,
        "average_price": (
            format(quote.average_price, "f") if quote.average_price is not None else None
        ),
        "price_change_pct": (
            format(quote.price_change_pct, "f") if quote.price_change_pct is not None else None
        ),
        "total_trades": quote.total_trades,
        "description": quote.description,
        "market_name": quote.market_name,
        "official_close_upgrade": "B3 daily COTAHIST CLOSE outranks same-day LAST when available",
        "payload_policy": "BOUNDED_JSON_RESPONSE",
    }


async def download_bmob3_web_quote(
    *,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> tuple[str, bytes]:
    if fetcher is None:
        from workers import fetch

        fetcher = fetch
    response = await fetcher(
        B3_QUOTE_URL,
        headers={
            "User-Agent": "Mozilla/5.0 otello-tracker/1.0 (+private research)",
            "Accept": "application/json",
            "Connection": "close",
        },
    )
    if not bool(getattr(response, "ok", False)):
        status = getattr(response, "status", "unknown")
        raise RuntimeError(f"B3 BMOB3 quote feilet med HTTP {status}")
    content_length = response.headers.get("content-length")
    if content_length:
        try:
            declared = int(str(content_length))
        except ValueError as exc:
            raise ValueError("Ugyldig Content-Length fra B3") from exc
        if declared > MAX_QUOTE_BYTES:
            raise ValueError("B3 quote response overstiger Worker-grensen")
    text = await response.text()
    payload = str(text).encode("utf-8")
    if len(payload) > MAX_QUOTE_BYTES:
        raise ValueError("B3 quote response overstiger Worker-grensen")
    if not payload.lstrip().startswith(b"{"):
        raise ValueError("B3 quote endpoint returnerte ikke JSON")
    return B3_QUOTE_URL, payload


async def _persist_quote(
    repository: D1WriteRepository,
    quote: Bmob3WebQuote,
    payload: bytes,
    *,
    source_url: str,
    feed_mode: str,
    external_id: str,
    document_type: str,
    title: str,
) -> int:
    digest = hashlib.sha256(payload).hexdigest()
    metadata = _quote_metadata(quote, feed_mode=feed_mode)
    if feed_mode == "EOD_LAST_QUOTE":
        metadata["price_semantics"] = "FINAL_DELAYED_WEB_QUOTE_NOT_COTAHIST_CLOSE"
    document_id = await repository.create_source_document(
        source_code="B3",
        external_id=external_id.format(digest=digest),
        document_type=document_type,
        title=title,
        url=source_url,
        published_at=quote.provider_at,
        content_sha256=digest,
        metadata=metadata,
    )
    return await repository.upsert_market_price(
        symbol=BMOB3_SYMBOL,
        observed_at=quote.observed_at,
        trading_date=quote.trading_date,
        price_type="LAST",
        price=format(quote.price, "f"),
        currency="BRL",
        source_code="B3",
        source_document_id=document_id,
        quality="DIRECT",
        metadata=metadata,
    )


async def refresh_bmob3_intraday_price(
    database: Any | None = None,
    *,
    repository: D1WriteRepository | None = None,
    now: datetime | None = None,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> dict[str, Any]:
    if repository is None:
        if database is None:
            raise ValueError("D1 database eller repository må oppgis")
        repository = D1WriteRepository(database)

    current = now or datetime.now(B3_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=B3_TZ)
    current = current.astimezone(B3_TZ)
    day = current.date()
    target_date = day.isoformat()

    if not is_b3_trading_day(day):
        return {"status": "skipped", "reason": "not_b3_trading_day", "target_date": target_date}
    start = ASH_WEDNESDAY_START if is_ash_wednesday(day) else INTRADAY_START
    if current.time().replace(tzinfo=None) < start:
        return {"status": "skipped", "reason": "before_b3_quote_window", "target_date": target_date}
    if current.time().replace(tzinfo=None) >= EOD_FINALIZE_AFTER:
        return {"status": "skipped", "reason": "eod_window_has_priority", "target_date": target_date}

    url, payload = await download_bmob3_web_quote(fetcher=fetcher)
    quote = parse_bmob3_web_quote(payload)
    if quote.trading_date != target_date:
        return {
            "status": "stale",
            "reason": "provider_date_mismatch",
            "target_date": target_date,
            "provider_date": quote.trading_date,
        }
    price_id = await _persist_quote(
        repository,
        quote,
        payload,
        source_url=url,
        feed_mode="DELAYED_INTRADAY",
        external_id="bmob3-web-quote-{digest:.20}",
        document_type="API_RESPONSE",
        title=f"B3 public BMOB3 delayed web quote {quote.provider_at}",
    )
    return {
        "status": "ok",
        "feed_mode": "delayed_intraday",
        "price_id": price_id,
        "price_type": "LAST",
        "quality": "DIRECT",
        "price_brl": format(quote.price, "f"),
        "trading_date": quote.trading_date,
        "observed_at": quote.observed_at,
        "provider_at": quote.provider_at,
        "delay_minutes": B3_PUBLIC_DELAY_MINUTES,
        "source_url": url,
    }


async def bmob3_eod_check_done(repository: D1WriteRepository, target_date: str) -> bool:
    row = await repository.first(
        """
        SELECT 1 AS ok
        FROM source_documents sd
        JOIN sources s ON s.id=sd.source_id
        WHERE s.code='B3' AND sd.external_id=?
        LIMIT 1
        """,
        (f"bmob3-eod-last-check-{target_date}",),
    )
    return row is not None


async def finalize_bmob3_eod_price(
    repository: D1WriteRepository,
    *,
    target_date: str,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> dict[str, Any]:
    if await bmob3_eod_check_done(repository, target_date):
        return {"status": "skipped", "reason": "eod_already_finalized", "target_date": target_date}

    url, payload = await download_bmob3_web_quote(fetcher=fetcher)
    quote = parse_bmob3_web_quote(payload)
    if quote.trading_date != target_date:
        return {
            "status": "stale",
            "reason": "provider_date_mismatch",
            "target_date": target_date,
            "provider_date": quote.trading_date,
        }
    price_id = await _persist_quote(
        repository,
        quote,
        payload,
        source_url=url,
        feed_mode="EOD_LAST_QUOTE",
        external_id=f"bmob3-eod-last-check-{target_date}",
        document_type="EOD_MARKET_DATA_CHECK",
        title=f"BMOB3 B3 delayed EOD last-quote check {target_date}",
    )
    return {
        "status": "ok",
        "feed_mode": "eod_last_quote",
        "target_date": target_date,
        "price_id": price_id,
        "price_type": "LAST",
        "quality": "DIRECT",
        "price_brl": format(quote.price, "f"),
        "observed_at": quote.observed_at,
        "provider_at": quote.provider_at,
        "delay_minutes": B3_PUBLIC_DELAY_MINUTES,
        "source_url": url,
    }


async def maybe_finalize_bmob3_eod(
    database: Any | None = None,
    *,
    repository: D1WriteRepository | None = None,
    now: datetime | None = None,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> dict[str, Any]:
    if repository is None:
        if database is None:
            raise ValueError("D1 database eller repository må oppgis")
        repository = D1WriteRepository(database)

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
    return await finalize_bmob3_eod_price(
        repository,
        target_date=target_date,
        fetcher=fetcher,
    )

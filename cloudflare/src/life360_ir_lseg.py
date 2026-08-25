from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Any, Awaitable, Callable

try:
    from .bounded_response import read_response_bytes
    from .r2_archive import archive_bytes
except ImportError:
    from bounded_response import read_response_bytes
    from r2_archive import archive_bytes

LIFE360_IR_HISTORY_URL = "https://investors.life360.com/stock-information/historic-price-lookup"
SOURCE_CODE = "LIFE360_IR_LSEG"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_FALLBACK_AGE_DAYS = 7


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() == "tr":
            self._row = []
        elif tag.lower() in {"th", "td"} and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in {"th", "td"} and self._row is not None and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif lowered == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None
            self._cell = None


def _normalized(value: str) -> str:
    return " ".join(value.lower().replace("\xa0", " ").split())


def _price(value: str) -> Decimal:
    cleaned = value.replace("$", "").replace(",", "").strip()
    try:
        parsed = Decimal(cleaned)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Ugyldig Life360 IR sluttkurs: {value!r}") from exc
    if not parsed.is_finite() or parsed <= 0 or parsed > Decimal("100000"):
        raise ValueError(f"Urimelig Life360 IR sluttkurs: {value!r}")
    return parsed


def parse_life360_ir_history(payload: bytes | str) -> list[dict[str, str]]:
    text = payload.decode("utf-8-sig", errors="strict") if isinstance(payload, bytes) else payload
    parser = _TableParser()
    parser.feed(text)

    header_index: int | None = None
    date_column: int | None = None
    close_column: int | None = None
    for index, row in enumerate(parser.rows):
        normalized = [_normalized(cell) for cell in row]
        for candidate in ("date requested", "date"):
            if candidate in normalized:
                date_column = normalized.index(candidate)
                break
        for candidate in ("closing price", "close", "close price"):
            if candidate in normalized:
                close_column = normalized.index(candidate)
                break
        if date_column is not None and close_column is not None:
            header_index = index
            break
        date_column = None
        close_column = None

    if header_index is None or date_column is None or close_column is None:
        raise ValueError("Life360 IR-tabellen mangler dato eller Closing Price")

    rows: list[dict[str, str]] = []
    for row in parser.rows[header_index + 1 :]:
        if max(date_column, close_column) >= len(row):
            continue
        raw_date = row[date_column].strip()
        raw_close = row[close_column].strip()
        if not raw_date or not raw_close:
            continue
        parsed_date: date | None = None
        for pattern in ("%B %d, %Y", "%b %d, %Y", "%m/%d/%Y"):
            try:
                parsed_date = datetime.strptime(raw_date, pattern).date()
                break
            except ValueError:
                continue
        if parsed_date is None:
            continue
        close = _price(raw_close)
        rows.append(
            {
                "trading_date": parsed_date.isoformat(),
                "observed_at": f"{parsed_date.isoformat()}T23:59:59Z",
                "price": format(close, "f"),
            }
        )

    if not rows:
        raise ValueError("Life360 IR-tabellen inneholdt ingen gyldige sluttkurser")
    rows.sort(key=lambda item: item["trading_date"])
    return rows


def select_fresh_close(rows: list[dict[str, str]], *, target_date: str) -> dict[str, str]:
    target = date.fromisoformat(target_date)
    eligible = [row for row in rows if row["trading_date"] <= target_date]
    if not eligible:
        raise ValueError(f"Life360 IR mangler sluttkurs på eller før {target_date}")
    selected = max(eligible, key=lambda item: item["trading_date"])
    price_date = date.fromisoformat(selected["trading_date"])
    age_days = (target - price_date).days
    if age_days < 0 or age_days > MAX_FALLBACK_AGE_DAYS:
        raise ValueError(
            f"Life360 IR siste sluttkurs er {age_days} dager gammel; maks er {MAX_FALLBACK_AGE_DAYS}"
        )
    return selected


async def _download(*, fetcher: Callable[..., Awaitable[Any]] | None = None) -> bytes:
    if fetcher is None:
        from workers import fetch

        fetcher = fetch
    response = await fetcher(
        LIFE360_IR_HISTORY_URL,
        headers={
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            "User-Agent": "OtelloTracker/1.0 (+https://otellotracker.com)",
        },
    )
    if not bool(getattr(response, "ok", False)):
        raise RuntimeError(
            f"Life360 IR/LSEG feilet med HTTP {getattr(response, 'status', 'unknown')}"
        )
    return await read_response_bytes(
        response,
        max_bytes=MAX_RESPONSE_BYTES,
        label="Life360 IR/LSEG historic price HTML",
    )


async def refresh_life360_ir_lif(
    repository,
    *,
    target_date: str,
    archive_bucket: Any | None = None,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> dict[str, Any]:
    payload = await _download(fetcher=fetcher)
    rows = parse_life360_ir_history(payload)
    selected = select_fresh_close(rows, target_date=target_date)
    digest = hashlib.sha256(payload).hexdigest()
    archived = (
        await archive_bytes(
            archive_bucket,
            payload,
            source="life360-ir-lseg",
            kind="historic-price-html",
            logical_date=target_date,
            filename=f"lif-{target_date}-{digest[:12]}.html",
        )
        if archive_bucket is not None
        else None
    )
    document_id = await repository.create_source_document(
        source_code=SOURCE_CODE,
        external_id=f"life360-ir-lseg:lif:{target_date}:{digest[:16]}",
        document_type="WEB_PAGE",
        title="Life360 LIF historic price lookup — LSEG",
        url=LIFE360_IR_HISTORY_URL,
        published_at=f"{target_date}T00:00:00Z",
        content_sha256=digest,
        metadata={
            "symbol": "LIF",
            "currency": "USD",
            "provider": "LSEG via Life360 Investor Relations",
            "publisher": "Life360 Investor Relations",
            "source_url": LIFE360_IR_HISTORY_URL,
            "source_policy": "INDEPENDENT_SECONDARY_FALLBACK",
            "price_type": "historical_closing_price",
            "adjusted": True,
            "fallback_only": True,
            "history_complete": False,
            "max_fallback_age_days": MAX_FALLBACK_AGE_DAYS,
            "r2_key": archived.get("r2_key") if archived else None,
        },
    )
    source_id = await repository.source_id(SOURCE_CODE)
    instrument_id = await repository.instrument_id("LIF")
    metadata_json = json.dumps(
        {
            "provider": "LSEG via Life360 Investor Relations",
            "publisher": "Life360 Investor Relations",
            "role": "NASDAQ_COMMON",
            "adjusted": True,
            "source_policy": "INDEPENDENT_SECONDARY_FALLBACK",
            "fallback_only": True,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    await repository.run(
        """
        INSERT INTO market_prices(
            instrument_id, observed_at, trading_date, price_type, price, currency,
            source_id, source_document_id, quality, metadata_json
        ) VALUES (?, ?, ?, 'CLOSE', ?, 'USD', ?, ?, 'DIRECT', ?)
        ON CONFLICT(instrument_id, observed_at, price_type, source_id)
        DO UPDATE SET
            trading_date=excluded.trading_date,
            price=excluded.price,
            currency=excluded.currency,
            source_document_id=excluded.source_document_id,
            quality=excluded.quality,
            metadata_json=excluded.metadata_json
        """,
        (
            instrument_id,
            selected["observed_at"],
            selected["trading_date"],
            selected["price"],
            source_id,
            document_id,
            metadata_json,
        ),
    )
    age_days = (
        date.fromisoformat(target_date) - date.fromisoformat(selected["trading_date"])
    ).days
    return {
        "status": "ok",
        "symbol": "LIF",
        "provider": "LSEG via Life360 Investor Relations",
        "source_code": SOURCE_CODE,
        "source_url": LIFE360_IR_HISTORY_URL,
        "currency": "USD",
        "price": selected["price"],
        "price_date": selected["trading_date"],
        "price_age_days": age_days,
        "rows_written": 1,
        "fallback_only": True,
        "history_backfill": False,
        "history_complete": False,
        "source_document_id": document_id,
        "content_sha256": digest,
        "r2_archive": archived,
    }

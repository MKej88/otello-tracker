from __future__ import annotations

import csv
import hashlib
import io
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Awaitable, Callable

from repository import D1WriteRepository

OTEC_ISIN = "NO0010040611"
OTEC_SYMBOL = "OTEC"
OSLO_VENUE = "XOSL"
TRADING_LOCATION = "OSL"
FILE_TYPE = "EQUITIES"
INTRADAY_SELECTIONS = ("LAST_15_MINUTES", "LAST_HOUR")
DOWNLOAD_URL = (
    "https://marketdata.euronext.com/data-reporting-service/trades-file/download/"
    "{file_type}/{time_selection}/{trading_location}"
)

# Phase 15.4.1 deliberately accepts only the small rolling Euronext windows. The
# parser streams the CSV member from the ZIP and never materialises the expanded
# CSV as one Python bytes/string object. A full trading-day payload belongs in the
# separate EOD/recovery step where its Worker/R2 strategy can be bounded explicitly.
MAX_INTRADAY_ZIP_BYTES = 24 * 1024 * 1024
MAX_INTRADAY_CSV_BYTES = 64 * 1024 * 1024
_REQUIRED_FIELDS = {
    "TradingDateTime",
    "PublicationDateTime",
    "MifidInstrumentID",
    "MifidPrice",
    "MifidQuantity",
    "MifidPriceNotation",
    "MifidCurrency",
    "Venue",
    "TradeUniqueIdentifier",
    "MissingPrice",
    "VenueOfPublication",
}


@dataclass(frozen=True)
class DelayedTrade:
    trading_datetime: str
    publication_datetime: str
    price: Decimal
    quantity: Decimal
    currency: str
    venue: str
    trade_unique_identifier: str
    venue_of_publication: str

    @property
    def trading_date(self) -> str:
        return self.trading_datetime[:10]


def _parse_utc_timestamp(value: str, *, field: str) -> datetime:
    raw = value.strip()
    if not raw:
        raise ValueError(f"Euronext mangler {field}")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Ugyldig Euronext {field}: {value!r}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"Euronext {field} mangler tidssone: {value!r}")
    return parsed.astimezone(UTC)


def _canonical_utc(value: str, *, field: str) -> str:
    return _parse_utc_timestamp(value, field=field).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def delayed_download_url(time_selection: str) -> str:
    selection = time_selection.strip().upper()
    if selection not in INTRADAY_SELECTIONS:
        raise ValueError(f"Ugyldig Worker intradag-selection: {time_selection}")
    return DOWNLOAD_URL.format(
        file_type=FILE_TYPE,
        time_selection=selection,
        trading_location=TRADING_LOCATION,
    )


def _normalise_header(line: str) -> list[str]:
    values = next(csv.reader([line]))
    return [value.strip().strip('"') for value in values]


def parse_euronext_intraday_trades(payload: bytes) -> list[DelayedTrade]:
    """Stream and parse only OTEC trades from a bounded delayed Euronext ZIP."""
    if not payload:
        raise ValueError("Euronext delayed endpoint returnerte tom fil")
    if len(payload) > MAX_INTRADAY_ZIP_BYTES:
        raise ValueError("Euronext intradag-ZIP overstiger Worker-grensen")

    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise ValueError("Euronext delayed-data er ikke en gyldig ZIP") from exc

    with archive:
        members = [name for name in archive.namelist() if not name.endswith("/")]
        csv_members = [name for name in members if name.lower().endswith(".csv")]
        if len(csv_members) != 1:
            raise ValueError(f"Euronext delayed ZIP forventet én CSV, fant {len(csv_members)}")
        info = archive.getinfo(csv_members[0])
        if info.file_size > MAX_INTRADAY_CSV_BYTES:
            raise ValueError("Euronext intradag-CSV overstiger Worker-grensen")

        with archive.open(csv_members[0], "r") as raw_stream:
            with io.TextIOWrapper(raw_stream, encoding="utf-8-sig", newline="") as text_stream:
                fieldnames: list[str] | None = None
                for _ in range(100):
                    line = text_stream.readline()
                    if not line:
                        break
                    candidate = _normalise_header(line)
                    if _REQUIRED_FIELDS <= set(candidate):
                        fieldnames = candidate
                        break
                if fieldnames is None:
                    raise ValueError("Fant ikke forventet Euronext trade-header")

                reader = csv.DictReader(text_stream, fieldnames=fieldnames)
                trades: list[DelayedTrade] = []
                for row in reader:
                    if (row.get("MifidInstrumentID") or "").strip() != OTEC_ISIN:
                        continue
                    if (row.get("MifidCurrency") or "").strip().upper() != "NOK":
                        continue
                    if (row.get("Venue") or "").strip().upper() != OSLO_VENUE:
                        continue
                    if (row.get("MifidPriceNotation") or "").strip().upper() != "MONE":
                        continue
                    if (row.get("MissingPrice") or "").strip():
                        continue
                    try:
                        price = Decimal((row.get("MifidPrice") or "").strip())
                        quantity = Decimal((row.get("MifidQuantity") or "").strip())
                    except (InvalidOperation, ValueError) as exc:
                        raise ValueError("Ugyldig pris/antall i OTEC-rad fra Euronext") from exc
                    if price <= 0 or quantity < 0:
                        raise ValueError(
                            "Ugyldig ikke-positiv OTEC-pris eller negativt antall fra Euronext"
                        )

                    trading_datetime = _canonical_utc(
                        row.get("TradingDateTime") or "", field="TradingDateTime"
                    )
                    publication_datetime = _canonical_utc(
                        row.get("PublicationDateTime") or "", field="PublicationDateTime"
                    )
                    if _parse_utc_timestamp(
                        publication_datetime, field="PublicationDateTime"
                    ) < _parse_utc_timestamp(trading_datetime, field="TradingDateTime"):
                        raise ValueError("Euronext PublicationDateTime er før TradingDateTime")

                    trades.append(
                        DelayedTrade(
                            trading_datetime=trading_datetime,
                            publication_datetime=publication_datetime,
                            price=price,
                            quantity=quantity,
                            currency="NOK",
                            venue=OSLO_VENUE,
                            trade_unique_identifier=(
                                row.get("TradeUniqueIdentifier") or ""
                            ).strip(),
                            venue_of_publication=(
                                row.get("VenueOfPublication") or ""
                            ).strip().upper(),
                        )
                    )
                return trades


def latest_otec_trade(payload: bytes) -> DelayedTrade | None:
    trades = parse_euronext_intraday_trades(payload)
    if not trades:
        return None
    return max(
        trades,
        key=lambda item: (
            _parse_utc_timestamp(item.trading_datetime, field="TradingDateTime"),
            _parse_utc_timestamp(item.publication_datetime, field="PublicationDateTime"),
            item.trade_unique_identifier,
        ),
    )


async def _response_bytes(response: Any) -> bytes:
    content_length = response.headers.get("content-length")
    if content_length:
        try:
            declared = int(str(content_length))
        except ValueError as exc:
            raise ValueError("Ugyldig Content-Length fra Euronext") from exc
        if declared > MAX_INTRADAY_ZIP_BYTES:
            raise ValueError("Euronext intradag-ZIP overstiger Worker-grensen")

    buffer = await response.arrayBuffer()
    try:
        from js import Uint8Array

        converted = Uint8Array.new(buffer).to_py()
    except (ImportError, AttributeError, TypeError):
        converter = getattr(buffer, "to_py", None)
        converted = converter() if callable(converter) else buffer

    if isinstance(converted, memoryview):
        payload = converted.tobytes()
    else:
        payload = bytes(converted)
    if len(payload) > MAX_INTRADAY_ZIP_BYTES:
        raise ValueError("Euronext intradag-ZIP overstiger Worker-grensen")
    return payload


async def download_euronext_intraday(
    time_selection: str,
    *,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> tuple[str, bytes]:
    selection = time_selection.strip().upper()
    url = delayed_download_url(selection)
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
        raise RuntimeError(f"Euronext delayed-data feilet med HTTP {status}")
    return url, await _response_bytes(response)


async def import_delayed_otec_trade(
    repository: D1WriteRepository,
    payload: bytes,
    *,
    time_selection: str,
    source_url: str,
) -> dict[str, Any]:
    trade = latest_otec_trade(payload)
    if trade is None:
        return {
            "found": False,
            "time_selection": time_selection,
            "source_url": source_url,
        }

    digest = hashlib.sha256(payload).hexdigest()
    metadata = {
        "feed": "DELAYED_PUBLIC_TRADE_FILE",
        "feed_mode": "WORKER_INTRADAY",
        "file_type": FILE_TYPE,
        "time_selection": time_selection,
        "trading_location": TRADING_LOCATION,
        "isin": OTEC_ISIN,
        "venue": trade.venue,
        "venue_of_publication": trade.venue_of_publication,
        "trade_unique_identifier": trade.trade_unique_identifier,
        "publication_datetime": trade.publication_datetime,
        "delay_policy": "EURONEXT_DELAYED_DATA_MAX_15_MINUTES",
        "price_semantics": "LATEST_REPORTED_TRADE_NOT_OFFICIAL_CLOSE",
        "payload_policy": "BOUNDED_ROLLING_WINDOW_STREAMED_ZIP_MEMBER",
    }
    document_id = await repository.create_source_document(
        source_code="EURONEXT",
        external_id=(
            f"otec-delayed-{time_selection.lower()}-{trade.trading_date}-{digest[:20]}"
        ),
        document_type="DELAYED_MARKET_DATA_FILE",
        title=f"Euronext delayed Oslo equity trades - {time_selection}",
        url=source_url,
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
        "found": True,
        "time_selection": time_selection,
        "price_id": price_id,
        "trading_date": trade.trading_date,
        "trading_datetime": trade.trading_datetime,
        "publication_datetime": trade.publication_datetime,
        "price_nok": format(trade.price, "f"),
        "quantity": format(trade.quantity, "f"),
        "trade_unique_identifier": trade.trade_unique_identifier,
        "source_url": source_url,
    }


async def refresh_otec_intraday(
    database: Any | None = None,
    *,
    repository: D1WriteRepository | None = None,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> dict[str, Any]:
    """Refresh the bounded OTEC rolling windows and persist the latest direct trade."""
    if repository is None:
        if database is None:
            raise ValueError("D1 database eller repository må oppgis")
        repository = D1WriteRepository(database)

    attempts: list[dict[str, Any]] = []
    for selection in INTRADAY_SELECTIONS:
        url, payload = await download_euronext_intraday(selection, fetcher=fetcher)
        result = await import_delayed_otec_trade(
            repository,
            payload,
            time_selection=selection,
            source_url=url,
        )
        attempts.append(result)
        if result.get("found"):
            return {
                "status": "ok",
                "feed_mode": "worker_intraday",
                "selected": selection,
                "attempts": attempts,
                **result,
            }
    return {
        "status": "no_trade",
        "feed_mode": "worker_intraday",
        "selected": None,
        "attempts": attempts,
    }

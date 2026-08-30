from __future__ import annotations

import csv
import hashlib
import io
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from app.db.connection import get_connection
from app.db.repository import create_source_document, upsert_market_price

OTEC_ISIN = "NO0010040611"
OTEC_SYMBOL = "OTEC"
OSLO_VENUE = "XOSL"
TRADING_LOCATION = "OSL"
FILE_TYPE = "EQUITIES"
DEFAULT_SELECTIONS = ("CURRENT_TRADING_DAY", "PREVIOUS_TRADING_DAY")
DOWNLOAD_URL = (
    "https://marketdata.euronext.com/data-reporting-service/trades-file/download/"
    "{file_type}/{time_selection}/{trading_location}"
)
MAX_ZIP_BYTES = 100 * 1024 * 1024
MAX_CSV_BYTES = 250 * 1024 * 1024
MAX_RETRY_DELAY_SECONDS = 60.0
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
    isin: str
    price: Decimal
    quantity: Decimal
    price_notation: str
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
    parsed = _parse_utc_timestamp(value, field=field)
    return parsed.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _extract_csv(payload: bytes) -> bytes:
    if len(payload) > MAX_ZIP_BYTES:
        raise ValueError("Euronext delayed ZIP overstiger sikker størrelsesgrense")
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            members = [name for name in archive.namelist() if not name.endswith("/")]
            csv_members = [name for name in members if name.lower().endswith(".csv")]
            if len(csv_members) != 1:
                raise ValueError(
                    f"Euronext delayed ZIP forventet én CSV, fant {len(csv_members)}"
                )
            info = archive.getinfo(csv_members[0])
            if info.file_size > MAX_CSV_BYTES:
                raise ValueError(
                    "Euronext delayed CSV overstiger sikker størrelsesgrense"
                )
            raw = archive.read(csv_members[0])
    except zipfile.BadZipFile as exc:
        raise ValueError("Euronext delayed-data er ikke en gyldig ZIP") from exc
    if len(raw) > MAX_CSV_BYTES:
        raise ValueError("Euronext delayed CSV overstiger sikker størrelsesgrense")
    return raw


def _header_index(lines: list[str]) -> int:
    for index, line in enumerate(lines[:100]):
        fields = {item.strip().strip('"') for item in line.split(",")}
        if _REQUIRED_FIELDS <= fields:
            return index
    raise ValueError("Fant ikke forventet Euronext trade-header")


def parse_euronext_delayed_trades(payload: bytes) -> list[DelayedTrade]:
    """Parse OTEC trades from Euronext's public delayed Oslo EQUITIES ZIP.

    The first CSV line is Euronext's delayed-data terms notice. The actual header follows
    on a later line and is found by required field names rather than a hard-coded row
    number. Only exact OTEC ISIN, NOK monetary prices and XOSL trades are accepted.
    """
    raw = _extract_csv(payload)
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("Euronext delayed CSV er ikke UTF-8") from exc
    lines = text.splitlines()
    start = _header_index(lines)
    reader = csv.DictReader(io.StringIO("\n".join(lines[start:])))
    fields = set(reader.fieldnames or [])
    missing = sorted(_REQUIRED_FIELDS - fields)
    if missing:
        raise ValueError(f"Euronext delayed CSV mangler felter: {', '.join(missing)}")

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
                isin=OTEC_ISIN,
                price=price,
                quantity=quantity,
                price_notation="MONE",
                currency="NOK",
                venue=OSLO_VENUE,
                trade_unique_identifier=(
                    row.get("TradeUniqueIdentifier") or ""
                ).strip(),
                venue_of_publication=(row.get("VenueOfPublication") or "")
                .strip()
                .upper(),
            )
        )
    return trades


def latest_otec_trade(payload: bytes) -> DelayedTrade | None:
    trades = parse_euronext_delayed_trades(payload)
    if not trades:
        return None
    return max(
        trades,
        key=lambda item: (
            _parse_utc_timestamp(item.trading_datetime, field="TradingDateTime"),
            _parse_utc_timestamp(
                item.publication_datetime, field="PublicationDateTime"
            ),
            item.trade_unique_identifier,
        ),
    )


def delayed_download_url(time_selection: str) -> str:
    selection = time_selection.strip().upper()
    if selection not in {
        "LAST_15_MINUTES",
        "LAST_HOUR",
        "CURRENT_TRADING_DAY",
        "SINCE_PREVIOUS_TRADING_DAY",
        "PREVIOUS_TRADING_DAY",
    }:
        raise ValueError(f"Ugyldig Euronext timeSelection: {time_selection}")
    return DOWNLOAD_URL.format(
        file_type=FILE_TYPE,
        time_selection=selection,
        trading_location=TRADING_LOCATION,
    )


def download_euronext_delayed_equities(
    time_selection: str,
    *,
    timeout: int = 120,
    attempts: int = 3,
) -> tuple[str, bytes]:
    url = delayed_download_url(time_selection)
    last_error: Exception | None = None
    for attempt in range(1, max(1, attempts) + 1):
        try:
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "otello-tracker/1.0 private-investor-dashboard",
                    "Accept": "application/zip,application/octet-stream,*/*;q=0.8",
                },
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = response.read(MAX_ZIP_BYTES + 1)
            if len(payload) > MAX_ZIP_BYTES:
                raise ValueError(
                    "Euronext delayed ZIP overstiger sikker størrelsesgrense"
                )
            if not payload:
                raise ValueError("Euronext delayed endpoint returnerte tom fil")
            return url, payload
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code != 429 and not 500 <= exc.code <= 599:
                break
            if attempt >= attempts:
                break
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            try:
                delay = (
                    float(retry_after)
                    if retry_after is not None
                    else 2 ** (attempt - 1)
                )
            except ValueError:
                delay = 2 ** (attempt - 1)
            time.sleep(min(max(delay, 0.0), MAX_RETRY_DELAY_SECONDS))
        except (OSError, TimeoutError, urllib.error.URLError, ValueError) as exc:
            last_error = exc
            if attempt >= attempts:
                break
            time.sleep(min(2 ** (attempt - 1), MAX_RETRY_DELAY_SECONDS))
    if isinstance(last_error, urllib.error.HTTPError):
        detail = f"HTTP {last_error.code}"
    else:
        detail = str(last_error)
    raise RuntimeError(f"Euronext delayed-data feilet for {time_selection}: {detail}")


def import_delayed_otec_trade(
    payload: bytes,
    *,
    time_selection: str,
    source_url: str,
    database_path: str | None = None,
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
    }
    with get_connection(database_path) as connection:
        # A delayed window changes throughout the session. Include the payload digest in
        # the source identity so an older price never ends up pointing to metadata/hash
        # from a later download. Repeating an identical payload remains idempotent.
        document_id = create_source_document(
            connection,
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
        price_id = upsert_market_price(
            connection,
            symbol=OTEC_SYMBOL,
            observed_at=trade.trading_datetime,
            trading_date=trade.trading_date,
            price_type="LAST",
            price=trade.price,
            currency=trade.currency,
            source_code="EURONEXT",
            source_document_id=document_id,
            quality="DIRECT",
            metadata=metadata,
        )
        connection.commit()
    return {
        "found": True,
        "time_selection": time_selection,
        "price_id": price_id,
        "trading_date": trade.trading_date,
        "trading_datetime": trade.trading_datetime,
        "publication_datetime": trade.publication_datetime,
        "price_nok": str(trade.price),
        "quantity": str(trade.quantity),
        "trade_unique_identifier": trade.trade_unique_identifier,
        "source_url": source_url,
    }


def refresh_otec_delayed_price(
    database_path: str | None = None,
    *,
    selections: Iterable[str] = DEFAULT_SELECTIONS,
    timeout: int = 120,
) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    for selection in selections:
        normalized = selection.strip().upper()
        url, payload = download_euronext_delayed_equities(normalized, timeout=timeout)
        result = import_delayed_otec_trade(
            payload,
            time_selection=normalized,
            source_url=url,
            database_path=database_path,
        )
        attempts.append(result)
        if result.get("found"):
            return {
                "status": "ok",
                "selected": normalized,
                "attempts": attempts,
                **result,
            }
    return {"status": "no_trade", "selected": None, "attempts": attempts}

from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime, time as dt_time
from decimal import Decimal, InvalidOperation
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo

from bounded_response import read_response_bytes
from oslo_calendar import is_oslo_bors_trading_day
from repository import D1WriteRepository

OTEC_ISIN = "NO0010040611"
OTEC_SYMBOL = "OTEC"
OSLO_VENUE = "XOSL"
TRADING_LOCATION = "OSL"
FILE_TYPE = "EQUITIES"
INTRADAY_SELECTIONS = ("LAST_15_MINUTES", "LAST_HOUR")
FULL_DAY_SELECTION = "CURRENT_TRADING_DAY"
DOWNLOAD_URL = (
    "https://marketdata.euronext.com/data-reporting-service/trades-file/download/"
    "{file_type}/{time_selection}/{trading_location}"
)
TRADES_PAGE_URL = "https://marketdata.euronext.com/data-reporting-service/trades-file"

OSLO_TZ = ZoneInfo("Europe/Oslo")
RECENT_POLL_COVERAGE_MINUTES = 75
INTRADAY_BOOTSTRAP_AFTER = dt_time(9, 15)
EOD_FINALIZE_AFTER = dt_time(16, 45)

# Rolling files are the normal 30-minute path. The compressed response is bounded and
# the expanded CSV member is read incrementally from the ZIP stream.
MAX_INTRADAY_ZIP_BYTES = 24 * 1024 * 1024
MAX_INTRADAY_CSV_BYTES = 64 * 1024 * 1024

# CURRENT_TRADING_DAY is used only for cold-start/gap recovery. A Python Worker has a
# 128 MiB memory ceiling, and JS ArrayBuffer -> Python conversion can temporarily create
# more than one representation of the compressed payload. Keep the ZIP cap conservative.
# Oversized files fail closed as PARTIAL and are a candidate for the R2/Workflow path in
# Phase 15.5/15.6 instead of risking an OOM. The expanded CSV is never materialised whole.
MAX_RECOVERY_ZIP_BYTES = 32 * 1024 * 1024
MAX_RECOVERY_CSV_BYTES = 256 * 1024 * 1024

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


def _as_oslo_datetime(value: datetime | None) -> datetime:
    current = value or datetime.now(OSLO_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=OSLO_TZ)
    return current.astimezone(OSLO_TZ)


def delayed_download_url(time_selection: str) -> str:
    selection = time_selection.strip().upper()
    if selection not in {*INTRADAY_SELECTIONS, FULL_DAY_SELECTION}:
        raise ValueError(f"Ugyldig Euronext time selection: {time_selection}")
    return DOWNLOAD_URL.format(
        file_type=FILE_TYPE,
        time_selection=selection,
        trading_location=TRADING_LOCATION,
    )


def _normalise_header(line: str) -> list[str]:
    values = next(csv.reader([line]))
    return [value.strip().strip('"') for value in values]


def _parse_euronext_trades(
    payload: bytes,
    *,
    max_zip_bytes: int,
    max_csv_bytes: int,
    payload_label: str,
) -> list[DelayedTrade]:
    """Parse only OTEC rows while streaming the expanded CSV member from a bounded ZIP."""
    if not payload:
        raise ValueError("Euronext delayed endpoint returnerte tom fil")
    if len(payload) > max_zip_bytes:
        raise ValueError(f"Euronext {payload_label}-ZIP overstiger Worker-grensen")

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
        if info.file_size > max_csv_bytes:
            raise ValueError(f"Euronext {payload_label}-CSV overstiger streaming-grensen")

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


def parse_euronext_intraday_trades(payload: bytes) -> list[DelayedTrade]:
    return _parse_euronext_trades(
        payload,
        max_zip_bytes=MAX_INTRADAY_ZIP_BYTES,
        max_csv_bytes=MAX_INTRADAY_CSV_BYTES,
        payload_label="intradag",
    )


def parse_euronext_recovery_trades(payload: bytes) -> list[DelayedTrade]:
    return _parse_euronext_trades(
        payload,
        max_zip_bytes=MAX_RECOVERY_ZIP_BYTES,
        max_csv_bytes=MAX_RECOVERY_CSV_BYTES,
        payload_label="recovery",
    )


def _latest_trade(
    trades: list[DelayedTrade],
    *,
    target_date: str | None = None,
) -> DelayedTrade | None:
    candidates = (
        trades
        if target_date is None
        else [trade for trade in trades if trade.trading_date == target_date]
    )
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda item: (
            _parse_utc_timestamp(item.trading_datetime, field="TradingDateTime"),
            _parse_utc_timestamp(item.publication_datetime, field="PublicationDateTime"),
            item.trade_unique_identifier,
        ),
    )


def latest_otec_trade(payload: bytes) -> DelayedTrade | None:
    return _latest_trade(parse_euronext_intraday_trades(payload))


def latest_otec_recovery_trade(
    payload: bytes,
    *,
    target_date: str | None = None,
) -> DelayedTrade | None:
    return _latest_trade(parse_euronext_recovery_trades(payload), target_date=target_date)


async def _response_bytes(
    response: Any,
    *,
    max_bytes: int,
    payload_label: str,
) -> bytes:
    return await read_response_bytes(
        response,
        max_bytes=max_bytes,
        label=f"Euronext {payload_label}-ZIP",
    )


async def _download_euronext(
    time_selection: str,
    *,
    max_bytes: int,
    payload_label: str,
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
    return url, await _response_bytes(
        response,
        max_bytes=max_bytes,
        payload_label=payload_label,
    )


async def download_euronext_intraday(
    time_selection: str,
    *,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> tuple[str, bytes]:
    selection = time_selection.strip().upper()
    if selection not in INTRADAY_SELECTIONS:
        raise ValueError(f"Ugyldig Worker intradag-selection: {time_selection}")
    return await _download_euronext(
        selection,
        max_bytes=MAX_INTRADAY_ZIP_BYTES,
        payload_label="intradag",
        fetcher=fetcher,
    )


async def download_euronext_recovery(
    *,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> tuple[str, bytes]:
    return await _download_euronext(
        FULL_DAY_SELECTION,
        max_bytes=MAX_RECOVERY_ZIP_BYTES,
        payload_label="recovery",
        fetcher=fetcher,
    )


async def import_delayed_otec_trade(
    repository: D1WriteRepository,
    payload: bytes,
    *,
    time_selection: str,
    source_url: str,
) -> dict[str, Any]:
    selection = time_selection.strip().upper()
    if selection == FULL_DAY_SELECTION:
        trade = latest_otec_recovery_trade(payload)
        payload_policy = "BOUNDED_FULL_DAY_ZIP_STREAMED_CSV_MEMBER"
        feed_mode = "WORKER_GAP_RECOVERY"
    else:
        trade = latest_otec_trade(payload)
        payload_policy = "BOUNDED_ROLLING_WINDOW_STREAMED_ZIP_MEMBER"
        feed_mode = "WORKER_INTRADAY"
    if trade is None:
        return {
            "found": False,
            "time_selection": selection,
            "source_url": source_url,
        }

    digest = hashlib.sha256(payload).hexdigest()
    metadata = {
        "feed": "DELAYED_PUBLIC_TRADE_FILE",
        "feed_mode": feed_mode,
        "file_type": FILE_TYPE,
        "time_selection": selection,
        "trading_location": TRADING_LOCATION,
        "isin": OTEC_ISIN,
        "venue": trade.venue,
        "venue_of_publication": trade.venue_of_publication,
        "trade_unique_identifier": trade.trade_unique_identifier,
        "publication_datetime": trade.publication_datetime,
        "delay_policy": "EURONEXT_DELAYED_DATA_MAX_15_MINUTES",
        "price_semantics": "LATEST_REPORTED_TRADE_NOT_OFFICIAL_CLOSE",
        "payload_policy": payload_policy,
    }
    document_id = await repository.create_source_document(
        source_code="EURONEXT",
        external_id=f"otec-delayed-{selection.lower()}-{trade.trading_date}-{digest[:20]}",
        document_type="DELAYED_MARKET_DATA_FILE",
        title=f"Euronext delayed Oslo equity trades - {selection}",
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
        "time_selection": selection,
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


def _otec_step_healthy(metadata_json: Any) -> bool:
    try:
        metadata = json.loads(str(metadata_json or "{}"))
    except (TypeError, json.JSONDecodeError):
        return False
    steps = metadata.get("steps")
    if isinstance(steps, dict):
        step = steps.get("otec_delayed")
        return isinstance(step, dict) and step.get("status") != "error"
    # Phase 15.4.1 wrote the OTEC result directly under `otec` and failed the job on
    # exceptions, so a successful/partial row with this key is healthy coverage.
    return isinstance(metadata.get("otec"), dict)


async def recent_otec_poll_covered(
    repository: D1WriteRepository,
    *,
    now: datetime,
) -> bool:
    rows = await repository.all(
        """
        SELECT finished_at, metadata_json
        FROM job_runs
        WHERE job_name='cloudflare_fast_refresh'
          AND status IN ('SUCCESS','PARTIAL')
          AND finished_at IS NOT NULL
        ORDER BY finished_at DESC, id DESC
        LIMIT 8
        """
    )
    current_utc = now.astimezone(UTC)
    for row in rows:
        if not _otec_step_healthy(row.get("metadata_json")):
            continue
        try:
            finished = _parse_utc_timestamp(str(row["finished_at"]), field="finished_at")
        except (KeyError, ValueError):
            continue
        age_seconds = (current_utc - finished).total_seconds()
        if 0 <= age_seconds <= RECENT_POLL_COVERAGE_MINUTES * 60:
            return True
        if age_seconds > RECENT_POLL_COVERAGE_MINUTES * 60:
            return False
    return False


async def refresh_otec_with_gap_recovery(
    database: Any | None = None,
    *,
    repository: D1WriteRepository | None = None,
    now: datetime | None = None,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> dict[str, Any]:
    """Refresh OTEC cheaply and use one bounded day file only when overlap is insufficient."""
    if repository is None:
        if database is None:
            raise ValueError("D1 database eller repository må oppgis")
        repository = D1WriteRepository(database)

    current = _as_oslo_datetime(now)
    small = await refresh_otec_intraday(repository=repository, fetcher=fetcher)
    if small.get("found"):
        return {"gap_recovery": False, **small}

    today = current.date()
    if not is_oslo_bors_trading_day(today):
        return {"gap_recovery": False, "gap_recovery_skipped": "not_trading_day", **small}
    if current.time().replace(tzinfo=None) < INTRADAY_BOOTSTRAP_AFTER:
        return {
            "gap_recovery": False,
            "gap_recovery_skipped": "before_bootstrap_cutoff",
            **small,
        }
    if await recent_otec_poll_covered(repository, now=current):
        return {
            "gap_recovery": False,
            "gap_recovery_skipped": "recent_poll_covered_by_last_hour",
            **small,
        }

    url, payload = await download_euronext_recovery(fetcher=fetcher)
    recovered = await import_delayed_otec_trade(
        repository,
        payload,
        time_selection=FULL_DAY_SELECTION,
        source_url=url,
    )
    return {
        "feed_mode": "worker_intraday",
        "gap_recovery": True,
        "small_windows": small,
        "status": "ok" if recovered.get("found") else "no_trade",
        "selected": FULL_DAY_SELECTION if recovered.get("found") else None,
        **recovered,
    }


async def eod_otec_check_done(repository: D1WriteRepository, target_date: str) -> bool:
    row = await repository.first(
        """
        SELECT 1 AS ok
        FROM source_documents sd
        JOIN sources s ON s.id=sd.source_id
        WHERE s.code='EURONEXT' AND sd.external_id=?
        LIMIT 1
        """,
        (f"otec-eod-last-check-{target_date}",),
    )
    return row is not None


async def _latest_stored_otec_for_date(
    repository: D1WriteRepository,
    target_date: str,
) -> dict[str, Any] | None:
    return await repository.first(
        """
        SELECT mp.id, mp.observed_at, mp.price, mp.currency, mp.source_document_id,
               mp.metadata_json
        FROM market_prices mp
        JOIN instruments i ON i.id=mp.instrument_id
        JOIN sources s ON s.id=mp.source_id
        WHERE i.symbol='OTEC'
          AND s.code='EURONEXT'
          AND mp.trading_date=?
          AND mp.price_type='LAST'
        ORDER BY mp.observed_at DESC, mp.id DESC
        LIMIT 1
        """,
        (target_date,),
    )


async def finalize_otec_eod_from_coverage(
    repository: D1WriteRepository,
    *,
    target_date: str,
    current_refresh: dict[str, Any],
) -> dict[str, Any]:
    """Finalize the session from rolling-feed coverage without claiming official CLOSE.

    A missing trade is intentionally non-terminal. The EOD marker is only written after
    a concrete stored trade exists, so a later scheduled run can retry and finalize the
    session if delayed data arrives after the first post-close poll.
    """
    if await eod_otec_check_done(repository, target_date):
        return {
            "status": "skipped",
            "reason": "eod_already_finalized",
            "target_date": target_date,
        }

    latest = await _latest_stored_otec_for_date(repository, target_date)
    if latest is None:
        return {
            "status": "no_trade",
            "feed_mode": "eod_last_trade",
            "target_date": target_date,
            "price_type": None,
            "quality": None,
            "finalization_method": "rolling_window_coverage",
            "retryable": True,
            "source_url": TRADES_PAGE_URL,
        }

    metadata: dict[str, Any] = {
        "feed": "DELAYED_PUBLIC_TRADE_FILE",
        "feed_mode": "EOD_LAST_TRADE",
        "target_date": target_date,
        "finalization_method": "ROLLING_WINDOW_COVERAGE",
        "current_refresh_status": current_refresh.get("status"),
        "current_refresh_selected": current_refresh.get("selected"),
        "current_refresh_gap_recovery": bool(current_refresh.get("gap_recovery")),
        "price_semantics": "FINAL_REPORTED_TRADE_NOT_OFFICIAL_CLOSE",
        "official_close_upgrade": "EWS prevInstrSess.closPx requires Euronext authKey",
        "payload_policy": "NO_FULL_DAY_FETCH_WHEN_ROLLING_COVERAGE_IS_CURRENT",
        "found": True,
    }
    document_id = await repository.create_source_document(
        source_code="EURONEXT",
        external_id=f"otec-eod-last-check-{target_date}",
        document_type="EOD_MARKET_DATA_CHECK",
        title=f"OTEC Euronext delayed EOD last-trade check {target_date}",
        url=TRADES_PAGE_URL,
        published_at=str(latest["observed_at"]),
        metadata={
            **metadata,
            "original_source_document_id": (
                int(latest["source_document_id"])
                if latest.get("source_document_id") is not None
                else None
            ),
        },
    )

    price_id = await repository.upsert_market_price(
        symbol=OTEC_SYMBOL,
        observed_at=str(latest["observed_at"]),
        trading_date=target_date,
        price_type="LAST",
        price=str(latest["price"]),
        currency=str(latest["currency"]),
        source_code="EURONEXT",
        source_document_id=document_id,
        quality="DIRECT",
        metadata={
            **metadata,
            "original_market_price_id": int(latest["id"]),
            "original_source_document_id": (
                int(latest["source_document_id"])
                if latest.get("source_document_id") is not None
                else None
            ),
        },
    )
    return {
        "status": "ok",
        "feed_mode": "eod_last_trade",
        "target_date": target_date,
        "price_id": price_id,
        "price_type": "LAST",
        "quality": "DIRECT",
        "price_semantics": "EOD_LAST_TRADE",
        "price_nok": str(latest["price"]),
        "trading_datetime": str(latest["observed_at"]),
        "finalization_method": "rolling_window_coverage",
        "source_url": TRADES_PAGE_URL,
    }


async def maybe_finalize_otec_eod(
    database: Any | None = None,
    *,
    repository: D1WriteRepository | None = None,
    now: datetime | None = None,
    current_refresh: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Finalize OTEC once after close when the current refresh proves live coverage."""
    if repository is None:
        if database is None:
            raise ValueError("D1 database eller repository må oppgis")
        repository = D1WriteRepository(database)

    current = _as_oslo_datetime(now)
    target_date = current.date().isoformat()
    if not is_oslo_bors_trading_day(current.date()):
        return {"status": "skipped", "reason": "not_trading_day", "target_date": target_date}
    if current.time().replace(tzinfo=None) < EOD_FINALIZE_AFTER:
        return {"status": "skipped", "reason": "before_eod_cutoff", "target_date": target_date}
    if await eod_otec_check_done(repository, target_date):
        return {"status": "skipped", "reason": "eod_already_finalized", "target_date": target_date}
    if not isinstance(current_refresh, dict):
        return {"status": "skipped", "reason": "missing_current_refresh", "target_date": target_date}
    if current_refresh.get("status") not in {"ok", "no_trade"}:
        return {"status": "skipped", "reason": "current_refresh_not_healthy", "target_date": target_date}

    return await finalize_otec_eod_from_coverage(
        repository,
        target_date=target_date,
        current_refresh=current_refresh,
    )

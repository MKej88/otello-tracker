from __future__ import annotations

import hashlib
import io
import zipfile
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Awaitable, Callable

try:
    from .b3_calendar import is_b3_trading_day
    from .bounded_response import read_response_bytes
    from .r2_archive import archive_bytes
except ImportError:
    from b3_calendar import is_b3_trading_day
    from bounded_response import read_response_bytes
    from r2_archive import archive_bytes

B3_DAILY_URL = (
    "https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_D{date_ddmmyyyy}.ZIP"
)
MAX_DAILY_ZIP_BYTES = 8 * 1024 * 1024
BMOB3_VOLUME_HISTORY_SESSIONS = 63
BMOB3_VOLUME_HISTORY_CALENDAR_DAYS = 100
BMOB3_VOLUME_HISTORY_BATCH_SIZE = 5


@dataclass(frozen=True)
class B3DailyClose:
    trading_date: str
    open: Decimal
    high: Decimal
    low: Decimal
    average: Decimal
    close: Decimal
    isin: str
    trades: int
    quantity: int
    volume: Decimal


def _implied_two_decimals(raw: str) -> Decimal:
    return Decimal(raw.strip() or "0") / Decimal("100")


def _integer(raw: str) -> int:
    return int(raw.strip() or "0")


def parse_bmob3_daily_zip(payload: bytes) -> list[B3DailyClose]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise ValueError("B3 COTAHIST er ikke en gyldig ZIP") from exc

    rows: list[B3DailyClose] = []
    with archive:
        members = [name for name in archive.namelist() if name.upper().endswith(".TXT")]
        if len(members) != 1:
            raise ValueError(f"Forventet én B3 COTAHIST TXT-fil, fant {len(members)}")
        with archive.open(members[0]) as raw:
            for raw_line in raw:
                line = raw_line.decode("latin-1").rstrip("\r\n")
                if len(line) < 245 or line[0:2] != "01":
                    continue
                if line[12:24].strip().upper() != "BMOB3":
                    continue
                if line[10:12] != "02" or line[24:27] != "010":
                    continue
                factor = _integer(line[210:217])
                if factor != 1:
                    raise ValueError(f"Uventet B3 quotation factor: {factor}")
                raw_date = line[2:10]
                trading_date = f"{raw_date[0:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
                date.fromisoformat(trading_date)
                rows.append(
                    B3DailyClose(
                        trading_date=trading_date,
                        open=_implied_two_decimals(line[56:69]),
                        high=_implied_two_decimals(line[69:82]),
                        low=_implied_two_decimals(line[82:95]),
                        average=_implied_two_decimals(line[95:108]),
                        close=_implied_two_decimals(line[108:121]),
                        isin=line[230:242].strip(),
                        trades=_integer(line[147:152]),
                        quantity=_integer(line[152:170]),
                        volume=_implied_two_decimals(line[170:188]),
                    )
                )
    return rows


async def _download_day(
    candidate: date,
    *,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> tuple[str, bytes] | None:
    if fetcher is None:
        from workers import fetch

        fetcher = fetch
    url = B3_DAILY_URL.format(date_ddmmyyyy=candidate.strftime("%d%m%Y"))
    response = await fetcher(
        url,
        headers={
            "Accept": "application/zip,application/octet-stream,*/*;q=0.8",
            "User-Agent": "otello-tracker/1.0 private-investor-dashboard",
        },
    )
    status = int(getattr(response, "status", 0) or 0)
    if status == 404:
        return None
    if not bool(getattr(response, "ok", False)):
        raise RuntimeError(f"B3 COTAHIST feilet med HTTP {status or 'unknown'}")
    payload = await read_response_bytes(
        response,
        max_bytes=MAX_DAILY_ZIP_BYTES,
        label=f"B3 COTAHIST {candidate.isoformat()}",
    )
    return url, payload


async def refresh_bmob3_close(
    repository,
    *,
    target_date: str,
    max_lookback_days: int = 10,
    archive_bucket: Any | None = None,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> dict[str, Any]:
    target = date.fromisoformat(target_date)
    attempted: list[str] = []
    for offset in range(max_lookback_days + 1):
        candidate = target - timedelta(days=offset)
        if not is_b3_trading_day(candidate):
            continue
        attempted.append(candidate.isoformat())
        downloaded = await _download_day(candidate, fetcher=fetcher)
        if downloaded is None:
            continue
        url, payload = downloaded
        rows = parse_bmob3_daily_zip(payload)
        if not rows:
            continue
        unexpected_dates = {
            row.trading_date
            for row in rows
            if row.trading_date != candidate.isoformat()
        }
        if unexpected_dates:
            raise ValueError(
                "B3 COTAHIST-dato matcher ikke forespurt handelsdag: "
                f"forventet {candidate.isoformat()}, fant "
                f"{', '.join(sorted(unexpected_dates))}"
            )
        latest = max(rows, key=lambda item: item.trading_date)
        digest = hashlib.sha256(payload).hexdigest()
        archived = (
            await archive_bytes(
                archive_bucket,
                payload,
                source="b3",
                kind="cotahist-daily",
                logical_date=candidate.isoformat(),
                filename=f"COTAHIST_D{candidate.strftime('%d%m%Y')}.ZIP",
            )
            if archive_bucket is not None
            else None
        )
        market_metadata = {
            "source": "B3_COTAHIST_DAILY",
            "open": format(latest.open, "f"),
            "high": format(latest.high, "f"),
            "low": format(latest.low, "f"),
            "average": format(latest.average, "f"),
            "trades": latest.trades,
            "volume_shares": latest.quantity,
            "volume_brl": format(latest.volume, "f"),
            "quotation_factor": 1,
            "r2_key": archived.get("r2_key") if archived else None,
        }
        document_id = await repository.create_source_document(
            source_code="B3",
            external_id=f"cotahist-daily:{candidate.isoformat()}",
            document_type="MARKET_DATA_FILE",
            title=f"B3 COTAHIST daily {candidate.isoformat()} - BMOB3",
            url=url,
            published_at=f"{candidate.isoformat()}T23:59:59Z",
            content_sha256=digest,
            metadata={
                "ticker": "BMOB3",
                "format": "COTAHIST",
                "scope": "DAILY",
                "isin": latest.isin,
                "workflow": "cloudflare_full_refresh",
                "archive_policy": (
                    "CONTENT_ADDRESSED_R2" if archived else "NOT_REQUESTED"
                ),
                **market_metadata,
            },
        )
        price_id = await repository.upsert_market_price(
            symbol="BMOB3",
            observed_at=f"{latest.trading_date}T23:59:59Z",
            trading_date=latest.trading_date,
            price_type="CLOSE",
            price=format(latest.close, "f"),
            currency="BRL",
            source_code="B3",
            source_document_id=document_id,
            quality="DIRECT",
            metadata=market_metadata,
        )
        return {
            "status": "ok",
            "trading_date": latest.trading_date,
            "price_brl": format(latest.close, "f"),
            "open_brl": format(latest.open, "f"),
            "high_brl": format(latest.high, "f"),
            "low_brl": format(latest.low, "f"),
            "volume_shares": latest.quantity,
            "price_id": price_id,
            "source_document_id": document_id,
            "attempted_dates": attempted,
            "r2_archive": archived,
        }

    return {
        "status": "not_available",
        "attempted_dates": attempted,
        "retryable": True,
    }


async def backfill_bmob3_volume_history(
    repository,
    *,
    target_date: str,
    required_sessions: int = BMOB3_VOLUME_HISTORY_SESSIONS,
    max_calendar_days: int = BMOB3_VOLUME_HISTORY_CALENDAR_DAYS,
    max_downloaded_sessions: int | None = None,
    archive_bucket: Any | None = None,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> dict[str, Any]:
    """Fill the rolling BMOB3 history used by the three-month volume average."""
    target = date.fromisoformat(target_date)
    start = (target - timedelta(days=max_calendar_days)).isoformat()
    rows = await repository.all(
        """
        SELECT DISTINCT mp.trading_date
        FROM market_prices mp
        JOIN instruments i ON i.id=mp.instrument_id
        JOIN sources s ON s.id=mp.source_id
        WHERE i.symbol='BMOB3' AND mp.price_type='CLOSE' AND s.code='B3'
          AND mp.trading_date BETWEEN ? AND ?
          AND json_extract(mp.metadata_json, '$.volume_shares') IS NOT NULL
        ORDER BY mp.trading_date DESC
        """,
        (start, target_date),
    )
    available = {str(row["trading_date"]) for row in rows}
    initial_sessions = len(available)
    downloaded = 0
    attempted: list[str] = []

    for offset in range(max_calendar_days + 1):
        if len(available) >= required_sessions:
            break
        if (
            max_downloaded_sessions is not None
            and downloaded >= max_downloaded_sessions
        ):
            break
        candidate = target - timedelta(days=offset)
        candidate_text = candidate.isoformat()
        if not is_b3_trading_day(candidate) or candidate_text in available:
            continue
        attempted.append(candidate_text)
        result = await refresh_bmob3_close(
            repository,
            target_date=candidate_text,
            max_lookback_days=0,
            archive_bucket=archive_bucket,
            fetcher=fetcher,
        )
        if result.get("status") != "ok":
            continue
        available.add(str(result["trading_date"]))
        downloaded += 1

    return {
        "status": "ok" if len(available) >= required_sessions else "partial",
        "required_sessions": required_sessions,
        "initial_sessions": initial_sessions,
        "available_sessions": len(available),
        "downloaded_sessions": downloaded,
        "attempted_dates": attempted,
    }

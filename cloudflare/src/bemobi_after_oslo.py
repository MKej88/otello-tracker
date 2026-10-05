"""Fixed, delayed BMOB3 reference at the latest Oslo closing auction.

B3's response clock minus its advertised 15-minute delay is an effective quote
time, not an exchange trade timestamp. The reference is explicitly approximate.
"""

from __future__ import annotations

import asyncio
import json
import math
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

try:
    from .b3_calendar import is_b3_trading_day
    from .oslo_calendar import _easter_sunday, is_oslo_bors_trading_day
except ImportError:
    from b3_calendar import is_b3_trading_day
    from oslo_calendar import _easter_sunday, is_oslo_bors_trading_day

OSLO_TZ = ZoneInfo("Europe/Oslo")
B3_TZ = ZoneInfo("America/Sao_Paulo")
REFERENCE_CRONS = ("40-42 14,15 * * 1-5", "20-22 11,12 * * 1-5")
REFERENCE_DELAY = timedelta(minutes=15)
REFERENCE_TOLERANCE = timedelta(minutes=3)
STATE_PREFIX = "bemobi_oslo_reference_v1:"


def iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def timestamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo is not None else None


def number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) and parsed > 0 else None


def closing_auction(day) -> datetime:
    # Wednesday before Easter is Oslo's recurring half trading day.
    half_day = day == _easter_sunday(day.year) - timedelta(days=4)
    return datetime.combine(day, time(13, 5) if half_day else time(16, 25), OSLO_TZ)


def latest_oslo_close(now: datetime) -> datetime:
    local = now.astimezone(OSLO_TZ)
    day = local.date()
    for _ in range(15):
        close = closing_auction(day)
        if is_oslo_bors_trading_day(day) and close <= local:
            return close
        day -= timedelta(days=1)
    raise ValueError("No recent Oslo trading day")


def capture_window(now: datetime) -> datetime | None:
    local = now.astimezone(OSLO_TZ)
    if not is_oslo_bors_trading_day(local.date()):
        return None
    close = closing_auction(local.date())
    start = close + REFERENCE_DELAY
    return close if start <= local <= start + REFERENCE_TOLERANCE else None


async def capture_reference(repository, *, now: datetime | None = None, fetcher=None):
    """Capture once per Oslo session; retries never overwrite a frozen reference."""
    try:
        from .bmob3_ingestion import (
            _persist_quote,
            download_bmob3_web_quote,
            parse_bmob3_web_quote,
        )
    except ImportError:
        from bmob3_ingestion import (
            _persist_quote,
            download_bmob3_web_quote,
            parse_bmob3_web_quote,
        )

    current = (now or datetime.now(UTC)).astimezone(UTC)
    close = capture_window(current)
    if close is None:
        return {"status": "skipped", "reason": "outside_reference_window"}
    if not is_b3_trading_day(current.astimezone(B3_TZ).date()):
        return {"status": "skipped", "reason": "not_b3_trading_day"}
    key = STATE_PREFIX + close.date().isoformat()
    if await repository.first("SELECT value FROM runtime_state WHERE key=?", (key,)):
        return {"status": "skipped", "reason": "reference_already_captured"}

    url, payload = await asyncio.wait_for(
        download_bmob3_web_quote(fetcher=fetcher), timeout=20
    )
    quote = parse_bmob3_web_quote(payload)
    if now is None:
        current = datetime.now(UTC)
    observed = timestamp(quote.observed_at)
    if (
        observed is None
        or number(quote.price) is None
        or abs(observed - close) > REFERENCE_TOLERANCE
        or not timedelta(seconds=-5)
        <= current - quote.provider_datetime
        <= timedelta(seconds=60)
    ):
        return {"status": "missing", "reason": "reference_timestamp_outside_tolerance"}
    price_id = await _persist_quote(
        repository,
        quote,
        payload,
        source_url=url,
        feed_mode="OSLO_CLOSE_REFERENCE",
        external_id="bmob3-oslo-reference-{digest:.20}",
        document_type="API_RESPONSE",
        title=f"BMOB3 reference for Oslo close {iso(close)}",
    )
    reference = {
        "price": str(quote.price),
        "observed_at": quote.observed_at,
        "oslo_close_at": iso(close),
        "source": "B3",
        "price_id": price_id,
        "delay_minutes": 15,
        "approximate": True,
    }
    await repository.run(
        "INSERT INTO runtime_state(key,value,updated_at) VALUES (?,?,?) "
        "ON CONFLICT(key) DO NOTHING",
        (key, json.dumps(reference, sort_keys=True), iso(current)),
    )
    return {"status": "ok", "reference": reference}


def _latest_expected_b3_day(now: datetime):
    local = now.astimezone(B3_TZ)
    day = local.date()
    if local.time().replace(tzinfo=None) < time(10, 15):
        day -= timedelta(days=1)
    for _ in range(15):
        if is_b3_trading_day(day):
            return day
        day -= timedelta(days=1)
    return day


async def bemobi_after_oslo(
    repository, *, now: datetime | None = None
) -> dict[str, Any]:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    close = latest_oslo_close(current)
    result: dict[str, Any] = {
        "ready": False,
        "status": "missing_reference",
        "symbol": "BMOB3",
        "currency": "BRL",
        "oslo_close_at": iso(close),
        "generated_at": iso(current),
        "points": [],
    }
    row = await repository.first(
        "SELECT value FROM runtime_state WHERE key=?",
        (STATE_PREFIX + close.date().isoformat(),),
    )
    if row is None:
        if current <= close + REFERENCE_DELAY + REFERENCE_TOLERANCE:
            result["status"] = "waiting_reference"
        return result
    try:
        reference = json.loads(row["value"])
    except (TypeError, ValueError):
        return result
    if not isinstance(reference, dict):
        return result
    reference_price = number(reference.get("price"))
    observed = timestamp(reference.get("observed_at"))
    if (
        reference_price is None
        or observed is None
        or observed > current
        or abs(observed - close) > REFERENCE_TOLERANCE
        or timestamp(reference.get("oslo_close_at")) != close
    ):
        return result
    result["reference"] = {**reference, "price": reference_price}
    # CLOSE rows can carry date-only/synthetic end-of-day clocks. Only timestamped
    # LAST quotes are valid evidence for movement after a particular intraday time.
    rows = await repository.all(
        """
        SELECT mp.id, mp.price, mp.observed_at, mp.trading_date, mp.metadata_json,
               s.code AS source
        FROM market_prices mp
        JOIN instruments i ON i.id=mp.instrument_id
        JOIN sources s ON s.id=mp.source_id
        WHERE i.symbol='BMOB3' AND mp.price_type='LAST'
          AND s.code IN ('B3','YAHOO_FINANCE')
          AND mp.trading_date BETWEEN ? AND ?
          AND julianday(mp.observed_at) > julianday(?)
          AND julianday(mp.observed_at) <= julianday(?)
        ORDER BY julianday(mp.observed_at) DESC,
                 CASE WHEN s.code='B3' THEN 0 ELSE 1 END, mp.id DESC
        LIMIT 150
        """,
        (
            observed.astimezone(B3_TZ).date().isoformat(),
            current.astimezone(B3_TZ).date().isoformat(),
            iso(observed),
            iso(current),
        ),
    )
    valid = [
        row
        for row in rows
        if number(row.get("price")) is not None
        and timestamp(row.get("observed_at")) is not None
    ]
    if not valid:
        result["status"] = "waiting_quote"
        return result
    latest = valid[0]
    latest_time = timestamp(latest["observed_at"])
    assert latest_time is not None
    local_now = current.astimezone(B3_TZ)
    active = is_b3_trading_day(local_now.date()) and time(
        10, 15
    ) <= local_now.time().replace(tzinfo=None) < time(19, 15)
    freshness_clock = (
        current
        if active
        else datetime.combine(
            _latest_expected_b3_day(current), time(19, 15), B3_TZ
        ).astimezone(UTC)
    )
    stale = latest_time.astimezone(B3_TZ).date() < _latest_expected_b3_day(current) or (
        freshness_clock - latest_time > timedelta(minutes=65)
    )
    try:
        metadata = json.loads(latest.get("metadata_json") or "{}")
    except (TypeError, ValueError):
        metadata = {}
    result["latest"] = {
        "price": number(latest["price"]),
        "observed_at": iso(latest_time),
        "source": latest["source"],
        "delay_minutes": metadata.get("public_delay_minutes")
        if isinstance(metadata, dict)
        else None,
    }
    if stale:
        result["status"] = "stale_quote"
        return result
    latest_price = number(latest["price"])
    assert latest_price is not None
    points = {iso(observed): {"at": iso(observed), "change_pct": 0.0}}
    for row in valid:  # preferred source wins duplicate timestamps
        at = iso(timestamp(row["observed_at"]))
        if at not in points:
            points[at] = {
                "at": at,
                "change_pct": (number(row["price"]) / reference_price - 1) * 100,
            }
    result.update(
        {
            "ready": True,
            "status": "ready",
            "change_pct": (latest_price / reference_price - 1) * 100,
            "change_brl": latest_price - reference_price,
            "points": sorted(points.values(), key=lambda point: point["at"]),
        }
    )
    return result


async def run_reference_capture(database, *, now: datetime | None = None):
    """Bounded scheduled job using the same writer lease as normal refreshes."""
    from job_lock import acquire_refresh_lock, release_refresh_lock
    from repository import D1WriteRepository

    current = (now or datetime.now(UTC)).astimezone(UTC)
    if capture_window(current) is None:
        return {"status": "skipped", "reason": "outside_reference_window"}
    repository = D1WriteRepository(database)
    lock = await acquire_refresh_lock(
        repository,
        owner=f"bemobi-reference:{iso(current)}",
        ttl_seconds=120,
    )
    if not lock.get("acquired"):
        return {"status": "skipped", "reason": "refresh_lock_held"}
    job_id = None
    try:
        job_id = await repository.start_job(
            job_name="cloudflare_bemobi_oslo_reference",
            started_at=iso(current),
            metadata={"oslo_close_reference": True},
        )
        # Validate the response against the real clock, including delayed execution.
        result = await capture_reference(repository)
        await repository.finish_job(
            job_id,
            finished_at=iso(datetime.now(UTC)),
            status="SUCCESS" if result["status"] in {"ok", "skipped"} else "PARTIAL",
            records_written=int(result["status"] == "ok"),
            metadata=result,
        )
        return result
    except Exception as exc:
        if job_id is not None:
            await repository.finish_job(
                job_id,
                finished_at=iso(datetime.now(UTC)),
                status="FAILED",
                error_message=f"{type(exc).__name__}: {str(exc)[:500]}",
            )
        raise
    finally:
        await release_refresh_lock(repository, lock.get("token"))

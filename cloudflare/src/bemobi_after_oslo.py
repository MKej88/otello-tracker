"""Fixed, delayed BMOB3 reference at the latest Oslo closing auction.

B3's response clock minus its advertised 15-minute delay is an effective quote
time, not an exchange trade timestamp. The reference is explicitly approximate.
"""

from __future__ import annotations

import asyncio
import json
import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

try:
    from .b3_calendar import b3_opening, is_b3_trading_day
    from .oslo_calendar import closing_auction, is_oslo_bors_trading_day
except ImportError:
    from b3_calendar import b3_opening, is_b3_trading_day
    from oslo_calendar import closing_auction, is_oslo_bors_trading_day

OSLO_TZ = ZoneInfo("Europe/Oslo")
B3_TZ = ZoneInfo("America/Sao_Paulo")
REFERENCE_CRONS = ("37-43 14,15 * * 1-5", "17-23 11,12 * * 1-5")
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
    return (
        close
        if start - REFERENCE_TOLERANCE <= local <= start + REFERENCE_TOLERANCE
        else None
    )


async def stored_reference(repository, close: datetime, current: datetime):
    rows = await repository.all(
        """SELECT mp.id, mp.price, mp.observed_at, mp.metadata_json
        FROM market_prices mp JOIN instruments i ON i.id=mp.instrument_id
        JOIN sources s ON s.id=mp.source_id
        WHERE i.symbol='BMOB3' AND s.code='B3' AND mp.price_type='LAST'
          AND mp.trading_date=?
          AND julianday(mp.observed_at) BETWEEN julianday(?) AND julianday(?)
          AND julianday(mp.observed_at)<=julianday(?)
        ORDER BY ABS(julianday(mp.observed_at)-julianday(?)),mp.id ASC LIMIT 20""",
        (
            close.astimezone(B3_TZ).date().isoformat(),
            iso(close - REFERENCE_TOLERANCE),
            iso(close + REFERENCE_TOLERANCE),
            iso(current),
            iso(close),
        ),
    )
    for row in rows:
        try:
            metadata = json.loads(row.get("metadata_json") or "{}")
        except (TypeError, ValueError):
            continue
        if (
            not isinstance(metadata, dict)
            or metadata.get("public_delay_minutes") != 15
            or number(row.get("price")) is None
        ):
            continue
        return {
            "price": str(row["price"]),
            "observed_at": row["observed_at"],
            "oslo_close_at": iso(close),
            "source": "B3",
            "price_id": row["id"],
            "delay_minutes": 15,
            "approximate": True,
            "recovered": True,
        }
    return None


def yahoo_reference_quote(payload, close: datetime, current: datetime):
    """Use only completed 1-minute bars ending at/before the closing auction."""
    from bmob3_ingestion import Bmob3YahooQuote, _validated_yahoo_result

    result, _, timezone_name = _validated_yahoo_result(json.loads(payload))
    times = result.get("timestamp")
    indicators = result.get("indicators")
    series = indicators.get("quote") if isinstance(indicators, dict) else None
    closes = (
        series[0].get("close")
        if isinstance(series, list) and len(series) == 1 and isinstance(series[0], dict)
        else None
    )
    if (
        not isinstance(times, list)
        or not isinstance(closes, list)
        or len(times) != len(closes)
    ):
        return None
    candidates = []
    for raw_time, raw_price in zip(times, closes, strict=True):
        if type(raw_time) is not int or raw_time % 60 or number(raw_price) is None:
            continue
        try:
            start = datetime.fromtimestamp(raw_time, UTC)
        except (ValueError, OverflowError, OSError):
            continue
        end = start + timedelta(minutes=1)
        if (
            start.astimezone(B3_TZ).date() == close.astimezone(B3_TZ).date()
            and close - REFERENCE_TOLERANCE <= end <= close
            and end <= current
        ):
            candidates.append((end, Decimal(str(raw_price))))
    if not candidates:
        return None
    end, price = max(candidates, key=lambda candidate: candidate[0])
    return Bmob3YahooQuote(price, end, timezone_name, None, None)


async def recover_reference(repository, *, now=None, fetcher=None):
    current = (now or datetime.now(UTC)).astimezone(UTC)
    close = latest_oslo_close(current)
    key = STATE_PREFIX + close.date().isoformat()
    if await repository.first("SELECT value FROM runtime_state WHERE key=?", (key,)):
        return {"status": "skipped", "reason": "reference_already_captured"}
    reference = await stored_reference(repository, close, current)
    if reference is None:
        # Give the primary B3 capture its full window. Later half-hour runs can
        # repair a missed capture from historical minute data, not today's LAST.
        if current <= close + REFERENCE_DELAY + REFERENCE_TOLERANCE:
            return {"status": "missing", "reason": "no_valid_stored_reference"}
        if not is_b3_trading_day(close.astimezone(B3_TZ).date()):
            return {"status": "missing", "reason": "not_b3_trading_day"}
        from bmob3_ingestion import download_bmob3_yahoo_quote, _persist_yahoo_quote

        try:
            url, payload, _, base = await asyncio.wait_for(
                download_bmob3_yahoo_quote(fetcher=fetcher), timeout=20
            )
            quote = yahoo_reference_quote(payload, close, current)
        except Exception as exc:
            return {
                "status": "missing",
                "reason": "historical_reference_unavailable",
                "error": f"{type(exc).__name__}: {str(exc)[:300]}",
            }
        if quote is None:
            return {"status": "missing", "reason": "no_valid_historical_reference"}
        # Persistence failures must remain visible to the scheduler.
        price_id = await _persist_yahoo_quote(
            repository,
            quote,
            payload,
            source_url=url,
            provider_base=base,
            fallback_reason="Missing B3 Oslo close reference; completed pre-close minute bar",
        )
        reference = {
            "price": str(quote.price),
            "observed_at": quote.observed_at,
            "oslo_close_at": iso(close),
            "source": "YAHOO_FINANCE",
            "source_url": url,
            "price_id": price_id,
            "approximate": True,
            "recovered": True,
            "basis": "COMPLETED_PRE_CLOSE_1M_BAR",
            "bar_start_at": iso(quote.provider_datetime - timedelta(minutes=1)),
        }
    await repository.run(
        "INSERT INTO runtime_state(key,value,updated_at) VALUES (?,?,?) ON CONFLICT(key) DO NOTHING",
        (key, json.dumps(reference, sort_keys=True), iso(current)),
    )
    return {"status": "ok", "reference": reference}


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


async def otec_close_basis(repository, close):
    day = close.astimezone(OSLO_TZ).date().isoformat()
    official = await repository.first(
        """SELECT mp.price,mp.price_type,mp.observed_at,s.code AS source
        FROM market_prices mp JOIN instruments i ON i.id=mp.instrument_id
        JOIN sources s ON s.id=mp.source_id
        WHERE i.symbol='OTEC' AND mp.trading_date=? AND mp.price_type='CLOSE'
        ORDER BY CASE s.code WHEN 'EURONEXT' THEN 0 ELSE 1 END,mp.id DESC LIMIT 1""",
        (day,),
    )
    if official and number(official.get("price")):
        return official
    # Match the closing-session window accepted by OTEC EOD finalization.
    # Euronext auction executions can be timestamped after the 16:25/13:05 anchor.
    auction_end = close + timedelta(minutes=5)
    rows = await repository.all(
        """SELECT mp.price,'LAST' AS price_type,mp.observed_at,s.code AS source
        FROM market_prices mp JOIN instruments i ON i.id=mp.instrument_id
        JOIN sources s ON s.id=mp.source_id
        WHERE i.symbol='OTEC' AND mp.trading_date=? AND mp.price_type='LAST'
          AND (julianday(mp.observed_at)<=julianday(?)
               OR (s.code='EURONEXT' AND julianday(mp.observed_at)<=julianday(?)))
        UNION ALL
        SELECT ma.last_price_nok AS price,'LAST' AS price_type,
               json_extract(ma.metadata_json,'$.latest_trade_at') AS observed_at,s.code AS source
        FROM market_activity ma JOIN instruments i ON i.id=ma.instrument_id
        JOIN sources s ON s.id=ma.source_id
        WHERE i.symbol='OTEC' AND ma.trading_date=? AND s.code='EURONEXT'
          AND julianday(json_extract(ma.metadata_json,'$.latest_trade_at'))<=julianday(?)
        ORDER BY observed_at DESC""",
        (day, iso(close), iso(auction_end), day, iso(auction_end)),
    )
    return next((row for row in rows if number(row.get("price"))), None)


async def otec_effect(repository, close: datetime, change_brl: float) -> dict[str, Any]:
    """Translate only the Bemobi price move, with FX and capital held at Oslo close."""
    day = close.astimezone(OSLO_TZ).date().isoformat()
    otec, fx, holding, shares = await asyncio.gather(
        otec_close_basis(repository, close),
        repository.first(
            """SELECT fr.rate, fr.observed_at, s.code AS source
            FROM fx_rates fr JOIN sources s ON s.id=fr.source_id
            WHERE fr.base_currency='BRL' AND fr.quote_currency='NOK'
              AND julianday(fr.observed_at) <= julianday(?)
              AND julianday(fr.observed_at) >= julianday(?)
            ORDER BY substr(fr.observed_at,1,10) DESC,
                     CASE s.code WHEN 'NORGES_BANK' THEN 0 WHEN 'ECB' THEN 1 ELSE 5 END,
                     julianday(fr.observed_at) DESC, fr.id DESC LIMIT 1""",
            (iso(close), iso(close - timedelta(days=7))),
        ),
        repository.first(
            """SELECT shares FROM bemobi_holdings WHERE effective_from <= ?
            AND (effective_to IS NULL OR effective_to >= ?)
            ORDER BY effective_from DESC, id DESC LIMIT 1""",
            (day, day),
        ),
        repository.first(
            """SELECT outstanding_shares FROM otello_share_counts WHERE effective_from <= ?
            AND (effective_to IS NULL OR effective_to >= ?)
            ORDER BY effective_from DESC, id DESC LIMIT 1""",
            (day, day),
        ),
    )
    missing = []
    if otec is None or number(otec.get("price")) is None:
        missing.append("otec_close")
    if fx is None or number(fx.get("rate")) is None:
        missing.append("fixed_fx")
    holding_number = number(holding.get("shares")) if holding else None
    if holding_number is None and (
        not holding or holding.get("shares") not in (0, "0")
    ):
        missing.append("bemobi_holding")
    if shares is None or number(shares.get("outstanding_shares")) is None:
        missing.append("otec_shares")
    if missing:
        return {"ready": False, "missing": missing}
    delta = (
        Decimal(str(change_brl))
        * Decimal(str(holding["shares"]))
        * Decimal(str(fx["rate"]))
        / Decimal(str(shares["outstanding_shares"]))
    )
    percent = delta / Decimal(str(otec["price"])) * 100
    if not math.isfinite(float(delta)) or not math.isfinite(float(percent)):
        return {"ready": False, "missing": ["invalid_calculation"]}
    return {
        "ready": True,
        "change_per_share_nok": float(delta),
        "change_pct": float(percent),
        "otec_price_nok": number(otec["price"]),
        "otec_price_type": otec["price_type"],
        "otec_observed_at": otec["observed_at"],
        "otec_source": otec["source"],
        "fixed_brl_nok": number(fx["rate"]),
        "fx_observed_at": fx["observed_at"],
        "fx_source": fx["source"],
        "holding_shares": holding["shares"],
        "otec_outstanding_shares": shares["outstanding_shares"],
    }


async def bemobi_after_oslo(
    repository, *, now: datetime | None = None
) -> dict[str, Any]:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    oslo_day = current.astimezone(OSLO_TZ).date()
    b3_day = current.astimezone(B3_TZ).date()
    if (
        is_oslo_bors_trading_day(oslo_day)
        and is_b3_trading_day(b3_day)
        and b3_opening(b3_day) <= current < closing_auction(oslo_day)
    ):
        # Today's B3 trading must never be measured against yesterday's Oslo
        # reference while Oslo is still trading. Gate on the actual opening,
        # independently of delayed quotes and without exposing the old basis.
        return {
            "ready": False,
            "status": "waiting_oslo_close",
            "symbol": "BMOB3",
            "currency": "BRL",
            "generated_at": iso(current),
            "points": [],
        }
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
        reference = await stored_reference(repository, close, current)
        if reference is None:
            if current <= close + REFERENCE_DELAY + REFERENCE_TOLERANCE:
                result["status"] = "waiting_reference"
            return result
    else:
        try:
            reference = json.loads(row["value"])
        except (TypeError, ValueError):
            return result
    try:
        reference = dict(reference)
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
    # This card measures movement since the latest Oslo close, not live freshness.
    # Outside overlapping trading hours, retain the latest validated quote until
    # a new Oslo close; the UI shows its actual timestamp across overnight gaps.
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
    result["otec_effect"] = await otec_effect(
        repository, close, latest_price - reference_price
    )
    return result


async def run_reference_capture(database, *, now: datetime | None = None):
    """Capture independent of NAV refreshes; all writes are idempotent.

    The per-day reference is protected by INSERT ... ON CONFLICT DO NOTHING.
    A long-running NAV writer must not make us miss the short quote window.
    """
    from repository import D1WriteRepository

    current = (now or datetime.now(UTC)).astimezone(UTC)
    if capture_window(current) is None:
        return {"status": "skipped", "reason": "outside_reference_window"}
    repository = D1WriteRepository(database)
    job_id = None
    try:
        job_id = await repository.start_job(
            job_name="cloudflare_bemobi_oslo_reference",
            started_at=iso(current),
            metadata={"oslo_close_reference": True},
        )
        # Validate the response against the real clock, including delayed execution.
        result = await asyncio.wait_for(capture_reference(repository), timeout=60)
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

"""Optional, license-gated indicative intraday BRL/NOK feed.

Never use for historical backfills, financial reporting or as an official FX fix.
The public API exposes FX values, so enabling this source additionally requires
written downstream redistribution permission from exchangerate.dev.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo

try:
    from .bounded_response import read_response_bytes
except ImportError:
    from bounded_response import read_response_bytes

SOURCE_CODE = "EXCHANGERATE_DEV"
URL = "https://api.exchangerate.dev/v1/latest/BRL?symbols=NOK"
OSLO = ZoneInfo("Europe/Oslo")
MAX_RESPONSE_BYTES = 32 * 1024
MAX_OBSERVATION_AGE = timedelta(minutes=75)
# A validated market quote must not vanish from the investor view overnight.
# Weekend carry is longer, but every response exposes its observation time.
MAX_MARKET_CARRY_AGE = timedelta(hours=24)
MAX_WEEKEND_CARRY_AGE = timedelta(hours=80)
MAX_NB_DEVIATION = Decimal("0.12")
MIN_RATE, MAX_RATE = Decimal("0.5"), Decimal("5")


def _timestamp(raw: Any) -> datetime:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("EXR missing observation timestamp")
    value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("EXR timestamp has no timezone")
    return value.astimezone(UTC)


def parse_brl_nok(payload: bytes | str | dict[str, Any], *, now: datetime) -> dict[str, Any]:
    data = json.loads(payload) if isinstance(payload, (str, bytes)) else payload
    if not isinstance(data, dict) or data.get("result") != "success" or data.get("base") != "BRL":
        raise ValueError("EXR unexpected response or currency")
    if data.get("source") != "live" or (data.get("sources") or {}).get("NOK") != "live":
        raise ValueError("EXR quote is not an intraday market observation")
    if data.get("market_session") != "open" or (data.get("stale") or {}).get("NOK") is not False:
        raise ValueError("EXR market is closed or FX observation is stale")
    raw_rate = (data.get("rates") or {}).get("NOK")
    try:
        rate = Decimal(str(raw_rate))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("EXR missing or invalid BRL/NOK rate") from exc
    if not rate.is_finite() or not (MIN_RATE <= rate <= MAX_RATE):
        raise ValueError("EXR BRL/NOK is outside sanity range")
    observed = _timestamp((data.get("effective_at") or {}).get("NOK"))
    now_utc = now.astimezone(UTC)
    if not timedelta(0) <= now_utc - observed <= MAX_OBSERVATION_AGE:
        raise ValueError("EXR observation is future-dated or too old")
    if observed.astimezone(OSLO).date() != now_utc.astimezone(OSLO).date():
        raise ValueError("EXR does not have an observation for current Oslo date")
    return {
        "rate": rate,
        "observed_at": observed.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "derived": "NOK" in (data.get("derived_symbols") or []),
        "source": "live",
        "age_minutes": round((now_utc - observed).total_seconds() / 60, 1),
    }



def _presentation_age_limit(now: datetime) -> timedelta:
    """Permit the latest verified market observation between trading sessions."""
    oslo_weekday = now.astimezone(OSLO).weekday()
    return MAX_WEEKEND_CARRY_AGE if oslo_weekday in {5, 6, 0} else MAX_MARKET_CARRY_AGE


async def _latest_saved_market_quote(
    repository: Any,
    *,
    now: datetime,
    before: datetime,
) -> dict[str, Any] | None:
    cutoff = (now - _presentation_age_limit(now)).isoformat(timespec="seconds").replace("+00:00", "Z")
    upper = min(before, now).isoformat(timespec="seconds").replace("+00:00", "Z")
    row = await repository.first(
        """SELECT fr.id, fr.observed_at,
                  substr(fr.observed_at, 1, 10) AS rate_date,
                  fr.rate, fr.source_document_id, s.code AS source_code
           FROM fx_rates fr
           JOIN sources s ON s.id=fr.source_id
           WHERE fr.base_currency='BRL' AND fr.quote_currency='NOK'
             AND s.code='EXCHANGERATE_DEV'
             AND fr.observed_at>=? AND fr.observed_at<=?
             AND CAST(fr.rate AS REAL)>0
           ORDER BY fr.observed_at DESC, fr.id DESC LIMIT 1""",
        (cutoff, upper),
    )
    if not row:
        return None
    try:
        observed = _timestamp(row["observed_at"])
        rate = Decimal(str(row["rate"]))
    except (ValueError, TypeError, InvalidOperation):
        return None
    if not rate.is_finite() or not MIN_RATE <= rate <= MAX_RATE:
        return None
    age = now - observed
    if not timedelta(0) <= age <= _presentation_age_limit(now):
        return None
    return {
        **row,
        "rate_date": observed.astimezone(OSLO).date().isoformat(),
        "age_minutes": round(age.total_seconds() / 60, 1),
        "carried_forward": age > MAX_OBSERVATION_AGE,
    }


async def latest_indicative_brl_nok(
    repository: Any, *, now: datetime | None = None
) -> dict[str, Any] | None:
    """Most recent validated EXR quote for display; never official history."""
    current = (now or datetime.now(UTC)).astimezone(UTC)
    return await _latest_saved_market_quote(repository, now=current, before=current)


async def current_indicative_brl_nok(
    repository: Any, *, day: str, now: datetime | None = None
) -> dict[str, Any] | None:
    """Use a validated EXR quote on its *own* Oslo date for live NAV.

    Previous-day quotes may carry overnight, but a later observation must
    never leak into an earlier NAV date or financial-report anchor.
    """
    current = (now or datetime.now(UTC)).astimezone(UTC)
    try:
        requested = datetime.strptime(day, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None
    if requested > current.astimezone(OSLO).date():
        return None
    next_day_start = datetime.combine(
        requested + timedelta(days=1), time.min, tzinfo=OSLO
    ).astimezone(UTC)
    # Historical valuations must never query live EXR quotes. This is also
    # important for repositories whose historical FX lookups use a different API.
    if next_day_start < current - _presentation_age_limit(current):
        return None
    row = await _latest_saved_market_quote(
        repository, now=current, before=next_day_start - timedelta(seconds=1),
    )
    return row if row and row["rate_date"] == day else None


async def refresh_exchangerate_dev_brl_nok(
    repository: Any,
    *,
    now: datetime | None = None,
    api_key: str | None = None,
    enabled: bool = False,
    license_approved: bool = False,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> dict[str, Any]:
    """Use at most one API call per scheduled fast-refresh; fail closed.

    Not enabled until permission covers existing public OtelloTracker API fields.
    """
    if not enabled:
        return {"status": "skipped", "reason": "feature_disabled", "network_fetches_avoided": True}
    if not license_approved:
        return {"status": "skipped", "reason": "license_not_approved", "network_fetches_avoided": True}
    # Public latest-rate endpoint permits anonymous requests. An optional
    # server-side key can be configured later; never expose it in the URL.
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    if moment.astimezone(OSLO).weekday() >= 5:
        return {"status": "skipped", "reason": "weekend", "network_fetches_avoided": True}

    if fetcher is None:
        from workers import fetch
        fetcher = fetch
    try:
        headers = {"Accept": "application/json"}
        if api_key and api_key.strip():
            headers["Authorization"] = f"Bearer {api_key.strip()}"
        response = await fetcher(URL, headers=headers)
        if not bool(getattr(response, "ok", False)):
            raise RuntimeError(f"HTTP {getattr(response, 'status', 'unknown')}")
        payload = await read_response_bytes(
            response, max_bytes=MAX_RESPONSE_BYTES, label="EXR BRL/NOK"
        )
        quote = parse_brl_nok(payload, now=moment)

        # Guard against a gross outlier before allowing it to influence NAV.
        nb = await repository.first(
            """SELECT fr.rate FROM fx_rates fr
               JOIN sources s ON s.id=fr.source_id
               WHERE s.code='NORGES_BANK' AND fr.base_currency='BRL'
                 AND fr.quote_currency='NOK'
                 AND fr.observed_at >= ?
               ORDER BY fr.observed_at DESC LIMIT 1""",
            ((moment - timedelta(days=7)).date().isoformat(),),
        )
        if nb is None:
            raise ValueError("missing Norges Bank reference for sanity check")
        official = Decimal(str(nb["rate"]))
        if official <= 0 or abs(quote["rate"] / official - 1) > MAX_NB_DEVIATION:
            raise ValueError("EXR deviates too far from Norges Bank")
        previous = await repository.first(
            """SELECT fr.observed_at, fr.rate FROM fx_rates fr
               JOIN sources s ON s.id=fr.source_id
               WHERE s.code=? AND fr.base_currency='BRL'
                 AND fr.quote_currency='NOK'
               ORDER BY fr.observed_at DESC LIMIT 1""",
            (SOURCE_CODE,),
        )
        if previous and quote["observed_at"] <= str(previous["observed_at"]):
            return {"status": "skipped", "reason": "observation_not_newer", "network_fetches_avoided": False}

        source_id = await repository.source_id(SOURCE_CODE)
        await repository.run(
            """INSERT INTO fx_rates(base_currency, quote_currency, observed_at, rate, source_id)
               VALUES ('BRL', 'NOK', ?, ?, ?)
               ON CONFLICT(base_currency, quote_currency, observed_at, source_id)
               DO UPDATE SET rate=excluded.rate,
                   fetched_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')""",
            (quote["observed_at"], format(quote["rate"], "f"), source_id),
        )
        return {
            "status": "ok",
            "rows_written": 1,
            "source": SOURCE_CODE,
            "observed_at": quote["observed_at"],
            "age_minutes": quote["age_minutes"],
            "derived": quote["derived"],
            "network_fetches_avoided": False,
        }
    except Exception as exc:
        # Important: no API key or raw response in job metadata or logs.
        return {
            "status": "skipped",
            "reason": "provider_unavailable_or_invalid",
            "error_type": type(exc).__name__,
            "network_fetches_avoided": False,
        }

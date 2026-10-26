"""Near-Oslo-close BRL/NOK reference using the existing delayed EXR feed.

Free EXR has no historical 1-minute retrieval. Instead, scheduled Oslo-close
reference minutes capture the quote *observed* near the close, roughly 15 min
after the event. Never infer the close from a daily Norges Bank fix.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

try:
    from .bemobi_after_oslo import capture_window, iso, timestamp
    from .exchangerate_dev_fx import URL, MAX_RESPONSE_BYTES, parse_brl_nok
    from .bounded_response import read_response_bytes
except ImportError:
    from bemobi_after_oslo import capture_window, iso, timestamp
    from exchangerate_dev_fx import URL, MAX_RESPONSE_BYTES, parse_brl_nok
    from bounded_response import read_response_bytes

REFERENCE_PREFIX = "brlnok_oslo_reference_v1:"
CLOSE_LOOKBACK = timedelta(minutes=3)
# Don't accept an FX observation after close; the indicator is then no
# longer an accurate close reference. Allow 5s rounding on the source clock.
CLOSE_FUTURE_TOLERANCE = timedelta(seconds=5)
MAX_NB_DEVIATION = Decimal("0.12")


async def fx_close_movement(repository: Any, close: datetime, current: datetime) -> dict[str, Any]:
    """Use only a proven near-close intraday reference and later EXR quotes."""
    key = REFERENCE_PREFIX + close.astimezone(ZoneInfo("Europe/Oslo")).date().isoformat()
    stored = await repository.first("SELECT value FROM runtime_state WHERE key=?", (key,))
    if not stored:
        return {"ready": False, "reason": "missing_oslo_close_fx_reference"}
    try:
        ref = json.loads(stored["value"])
        close_time = timestamp(ref.get("oslo_close_at"))
        observed = timestamp(ref.get("observed_at"))
        rate = Decimal(str(ref.get("rate")))
    except (TypeError, ValueError, ArithmeticError):
        return {"ready": False, "reason": "invalid_oslo_close_fx_reference"}
    if (
        close_time != close
        or observed is None
        or observed < close - CLOSE_LOOKBACK
        or observed > close + CLOSE_FUTURE_TOLERANCE
        or not rate.is_finite()
        or rate <= 0
        or ref.get("source") != "EXCHANGERATE_DEV"
    ):
        return {"ready": False, "reason": "invalid_oslo_close_fx_reference"}
    latest = await repository.first(
        """SELECT fr.rate, fr.observed_at, s.code AS source
           FROM fx_rates fr JOIN sources s ON s.id=fr.source_id
           WHERE fr.base_currency='BRL' AND fr.quote_currency='NOK'
             AND s.code='EXCHANGERATE_DEV'
             AND julianday(fr.observed_at)>julianday(?)
             AND julianday(fr.observed_at)<=julianday(?)
           ORDER BY julianday(fr.observed_at) DESC, fr.id DESC LIMIT 1""",
        (iso(close), iso(current)),
    )
    if not latest:
        return {"ready": False, "reason": "missing_fx_after_oslo_close", "reference_rate": float(rate), "reference_at": iso(observed)}
    try:
        recent = Decimal(str(latest["rate"]))
        latest_at = timestamp(latest.get("observed_at"))
    except (TypeError, ValueError, ArithmeticError):
        return {"ready": False, "reason": "invalid_latest_fx"}
    if not recent.is_finite() or recent <= 0 or latest_at is None:
        return {"ready": False, "reason": "invalid_latest_fx"}
    return {
        "ready": True,
        "reference_rate": float(rate),
        "reference_at": iso(observed),
        "reference_source": "EXCHANGERATE_DEV",
        "reference_approximate": True,
        "reference_offset_seconds": int((observed - close).total_seconds()),
        "latest_rate": float(recent),
        "latest_at": iso(latest_at),
        "latest_source": "EXCHANGERATE_DEV",
        "change_pct": float((recent / rate - 1) * 100),
    }


async def capture_fx_close_reference(
    repository: Any,
    *,
    now: datetime,
    enabled: bool,
    license_approved: bool,
    api_key: str | None,
    fetcher=None,
) -> dict[str, Any]:
    """Best-effort one-reference-per-day capture during B3 reference cron."""
    if not enabled or not license_approved:
        return {"status": "skipped", "reason": "fx_disabled_or_not_approved"}
    close = capture_window(now)
    if close is None:
        return {"status": "skipped", "reason": "outside_reference_window"}
    key = REFERENCE_PREFIX + close.astimezone(ZoneInfo("Europe/Oslo")).date().isoformat()
    existing = await repository.first("SELECT value FROM runtime_state WHERE key=?", (key,))
    if existing:
        return {"status": "skipped", "reason": "already_captured"}
    if fetcher is None:
        from workers import fetch
        fetcher = fetch
    try:
        headers = {"Accept": "application/json"}
        if api_key and api_key.strip():
            headers["Authorization"] = f"Bearer {api_key.strip()}"
        response = await fetcher(URL, headers=headers)
        if not getattr(response, "ok", False):
            return {"status": "skipped", "reason": "upstream_error", "http_status": getattr(response, "status", None)}
        data = await read_response_bytes(response, max_bytes=MAX_RESPONSE_BYTES, label="EXR close BRL/NOK")
        quote = parse_brl_nok(data, now=now)
        observed = timestamp(quote["observed_at"])
        if (
            observed is None
            or observed < close - CLOSE_LOOKBACK
            or observed > close + CLOSE_FUTURE_TOLERANCE
        ):
            return {
                "status": "skipped",
                "reason": "observation_not_near_oslo_close",
                "observed_at": quote["observed_at"],
                "close_at": iso(close),
            }
        nb = await repository.first(
            """SELECT fr.rate FROM fx_rates fr JOIN sources s ON s.id=fr.source_id
               WHERE s.code='NORGES_BANK' AND fr.base_currency='BRL'
                 AND fr.quote_currency='NOK' AND julianday(fr.observed_at)<=julianday(?)
               ORDER BY julianday(fr.observed_at) DESC LIMIT 1""",
            (iso(close),),
        )
        if not nb:
            return {"status": "skipped", "reason": "missing_sanity_reference"}
        nb_rate = Decimal(str(nb["rate"]))
        if nb_rate <= 0 or abs(quote["rate"] / nb_rate - 1) > MAX_NB_DEVIATION:
            return {"status": "skipped", "reason": "deviation_from_official_rate"}
        source_id = await repository.source_id("EXCHANGERATE_DEV")
        await repository.run(
            """INSERT INTO fx_rates(base_currency,quote_currency,observed_at,rate,source_id)
               VALUES ('BRL','NOK',?,?,?)
               ON CONFLICT(base_currency,quote_currency,observed_at,source_id)
               DO NOTHING""",
            (quote["observed_at"], format(quote["rate"], "f"), source_id),
        )
        reference = {
            "rate": format(quote["rate"], "f"),
            "observed_at": quote["observed_at"],
            "oslo_close_at": iso(close),
            "source": "EXCHANGERATE_DEV",
            "approximate": True,
            "delay_minutes": 15,
        }
        await repository.run(
            """INSERT INTO runtime_state(key,value,updated_at) VALUES (?,?,?)
               ON CONFLICT(key) DO NOTHING""",
            (key, json.dumps(reference, sort_keys=True), iso(now)),
        )
        return {"status": "ok", "observed_at": quote["observed_at"], "close_at": iso(close)}
    except Exception as exc:
        # Do not log the key, raw response, or stack traces containing headers.
        return {"status": "skipped", "reason": "provider_error", "error_type": type(exc).__name__}


async def run_fx_close_capture(database: Any, *, now: datetime, enabled: bool, approved: bool, api_key: str | None) -> dict[str, Any]:
    """Independent best-effort reference job: Bemobi capture must not block it."""
    from repository import D1WriteRepository
    repository = D1WriteRepository(database)
    if capture_window(now) is None:
        return {"status": "skipped", "reason": "outside_reference_window"}
    result = await capture_fx_close_reference(
        repository, now=now, enabled=enabled, license_approved=approved, api_key=api_key,
    )
    # Explicit, non-secret result for later read-only production diagnostics.
    await repository.run(
        """INSERT INTO runtime_state(key,value,updated_at) VALUES (?,?,?)
           ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
        ("brlnok_oslo_capture_last_result", json.dumps(result, sort_keys=True), iso(now)),
    )
    return result

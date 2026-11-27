#!/usr/bin/env python3
"""Bounded read-only D1 diagnostics for the latest completed Oslo session."""
from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from oslo_calendar import closing_auction, is_oslo_bors_trading_day

BASE = "https://api.cloudflare.com/client/v4"
OSLO = ZoneInfo("Europe/Oslo")
ALLOWED = {
    "ok", "skipped", "missing", "error", "already_captured",
    "awaiting_closer_reference", "observation_not_near_oslo_close",
    "fx_disabled_or_not_approved", "upstream_error", "provider_error",
    "missing_sanity_reference", "deviation_from_official_rate",
    "recovered_from_stored_quote", "no_valid_stored_reference",
}


def iso(dt):
    return dt.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def latest_close(now):
    day = now.astimezone(OSLO).date()
    for _ in range(15):
        close = closing_auction(day)
        if is_oslo_bors_trading_day(day) and close <= now:
            return close
        day -= timedelta(days=1)
    raise ValueError("missing Oslo close")


def safe_time(value):
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return iso(dt) if dt.tzinfo else None
    except ValueError:
        return None


def safe_attempt(row):
    try:
        value = json.loads(row["value"])
    except (KeyError, TypeError, ValueError):
        value = {}
    if not isinstance(value, dict):
        value = {}
    return {
        "checked_at": safe_time(row.get("updated_at")),
        "status": value.get("status") if value.get("status") in ALLOWED else None,
        "reason": value.get("reason") if value.get("reason") in ALLOWED else None,
        "observed_at": safe_time(value.get("observed_at")),
    }


def main():
    token = os.environ["CLOUDFLARE_API_TOKEN"]
    account = os.environ["CLOUDFLARE_ACCOUNT_ID"]
    name = os.environ["D1_DATABASE_NAME"]
    if not token or not re.fullmatch(r"[A-Za-z0-9_-]+", account):
        raise ValueError("missing or invalid read-only configuration")

    def request(path, payload=None):
        req = Request(BASE + path, data=json.dumps(payload).encode() if payload else None,
                      headers={"Authorization": "Bearer " + token,
                               "Content-Type": "application/json"})
        with urlopen(req, timeout=20) as response:
            body = response.read(262145)
        if len(body) > 262144:
            raise ValueError("D1 response too large")
        data = json.loads(body)
        if not data.get("success"):
            raise RuntimeError("D1 request failed")
        return data["result"]

    prefix = f"/accounts/{account}/d1/database"
    databases = request(prefix + "?" + urlencode({"name": name, "per_page": 50}))
    ids = [row["uuid"] for row in databases if row.get("name") == name]
    if len(ids) != 1 or not re.fullmatch(r"[A-Za-z0-9_-]+", ids[0]):
        raise ValueError("D1 database not uniquely resolved")

    def select(sql, params):
        result = request(prefix + "/" + ids[0] + "/query", {"sql": sql, "params": params})
        if len(result) != 1 or not result[0].get("success"):
            raise RuntimeError("D1 select failed")
        return result[0]["results"]

    close = latest_close(datetime.now(UTC))
    day = close.astimezone(OSLO).date().isoformat()
    quotes = select(
        """SELECT fr.observed_at FROM fx_rates fr JOIN sources s ON s.id=fr.source_id
           WHERE s.code='EXCHANGERATE_DEV' AND fr.base_currency='BRL'
             AND fr.quote_currency='NOK'
             AND julianday(fr.observed_at) BETWEEN julianday(?) AND julianday(?)
           ORDER BY julianday(fr.observed_at) LIMIT 100""",
        [iso(close-timedelta(minutes=10)), iso(close+timedelta(minutes=60))],
    )
    attempts = select(
        """SELECT key,value,updated_at FROM runtime_state
           WHERE key LIKE ? OR (key='brlnok_oslo_capture_last_result'
             AND julianday(updated_at) BETWEEN julianday(?) AND julianday(?))
           ORDER BY updated_at LIMIT 30""",
        ["brlnok_oslo_capture_attempt:" + day + ":%", iso(close), iso(close+timedelta(hours=1))],
    )
    ref = select("SELECT value,updated_at FROM runtime_state WHERE key=?",
                 ["brlnok_oslo_reference_v1:" + day])
    print(json.dumps({
        "oslo_close": iso(close),
        "reference_exists": bool(ref),
        "stored_observations": [safe_time(row.get("observed_at")) for row in quotes],
        "capture_attempts": [safe_attempt(row) for row in attempts],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        # Never log provider bodies, secrets or authenticated request URLs.
        print("D1-diagnose feilet: " + type(exc).__name__)
        raise SystemExit(1)

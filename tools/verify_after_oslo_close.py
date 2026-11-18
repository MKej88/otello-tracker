#!/usr/bin/env python3
"""Read-only production probe of post-close BMOB3, BRL/NOK and OTEC cards.

Runs in GitHub Actions near 17:15 Europe/Oslo (13:55 on the Easter half-day).
Never invents missing close benchmarks and never prints provider payloads.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime, timedelta
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from oslo_calendar import closing_auction, is_oslo_bors_trading_day

OSLO = ZoneInfo("Europe/Oslo")


def should_verify(now: datetime) -> bool:
    local = now.astimezone(OSLO)
    if not is_oslo_bors_trading_day(local.date()):
        return False
    delta = now - closing_auction(local.date())
    return timedelta(minutes=38) <= delta <= timedelta(minutes=75)


def evaluate(payload: dict, *, require_fx: bool = True) -> list[str]:
    problems: list[str] = []
    status = payload.get("status")
    if payload.get("ready") is not True or status != "ready":
        problems.append("bemobi:" + str(status or "missing"))
    fx = payload.get("fx_movement")
    if require_fx and (not isinstance(fx, dict) or fx.get("ready") is not True):
        problems.append("brlnok:" + str((fx or {}).get("reason", "missing")))
    effect = payload.get("otec_effect")
    if not isinstance(effect, dict) or effect.get("ready") is not True:
        problems.append("otec:missing_effect")
    return problems


def fetch_json(url: str) -> dict:
    for attempt in range(2):
        try:
            req = Request(url, headers={"Accept": "application/json", "Cache-Control": "no-cache"})
            with urlopen(req, timeout=12) as response:
                if response.status != 200:
                    raise ValueError("unexpected_http_status")
                body = response.read(131073)
                if len(body) > 131072:
                    raise ValueError("api_response_too_large")
                payload = json.loads(body)
                if not isinstance(payload, dict):
                    raise ValueError("response_not_object")
                return payload
        except Exception:
            if attempt:
                raise
            time.sleep(2)
    raise RuntimeError("unreachable")


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Oslo-close production check")
    parser.add_argument("--url", default="https://otellotracker.com/api/market/bemobi-after-oslo")
    parser.add_argument("--no-fx", action="store_true", help="Only if FX feed intentionally disabled")
    parser.add_argument("--force", action="store_true", help="Run outside regular time window")
    args = parser.parse_args()

    now = datetime.now(UTC)
    if not args.force and not should_verify(now):
        print("SKIPPED: not within the Oslo post-close verification window")
        return 0
    try:
        response = fetch_json(args.url)
    except Exception as exc:
        print("FAILURE: market API unavailable (" + type(exc).__name__ + ")")
        return 1

    issues = evaluate(response, require_fx=not args.no_fx)
    if response.get("oslo_close_at") != closing_auction(now.astimezone(OSLO).date()).astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"):
        issues.append("session:wrong_close_date")
    if issues:
        print("FAILURE: " + ", ".join(issues))
        diagnostics = response.get("refresh_diagnostics") or {}
        if isinstance(diagnostics, dict):
            for name in ("bemobi_reference", "bemobi_quote", "fx_reference", "fx_quote"):
                item = diagnostics.get(name) or {}
                if isinstance(item, dict):
                    print(name + ": status=" + str(item.get("status", "-")) +
                          ", reason=" + str(item.get("reason", "-")) +
                          ", error_type=" + str(item.get("error_type", "-")))
        return 1
    print("OK: current Oslo close, Bemobi and BRL/NOK movement, and OTEC effect verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())

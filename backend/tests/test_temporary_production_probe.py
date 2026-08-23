from __future__ import annotations

import json
from urllib.request import Request, urlopen

# Fersk produksjonsprobe 2026-08-23 ca. 07:32 Oslo.

def _get(path: str) -> dict:
    req = Request(
        f"https://otellotracker.com{path}",
        headers={"User-Agent": "otello-nightly-diagnostic/1.0"},
    )
    with urlopen(req, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def test_temporary_production_nightly_probe() -> None:
    payload = {
        "runtime": _get("/api/dashboard/runtime-status"),
        "report": _get("/api/dashboard/report-status"),
        "economic": _get("/api/dashboard/economic"),
        "health": _get("/api/health"),
    }
    raise AssertionError("TEMP_PRODUCTION_PROBE=" + json.dumps(payload, ensure_ascii=False, sort_keys=True))

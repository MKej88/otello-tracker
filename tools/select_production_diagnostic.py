"""Pick real Cloudflare production checks, never offline CI jobs."""
from __future__ import annotations
from datetime import UTC, datetime, timedelta
from typing import Any


def select_production_diagnostic(
    runs: list[dict[str, Any]], *, scheduled: bool, now: datetime
) -> dict[str, Any]:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    allowed_events = {"schedule"} if scheduled else {"schedule", "workflow_dispatch"}
    candidates = []
    for run in runs:
        if (run.get("event") not in allowed_events or
            run.get("head_branch") != "main" or
            run.get("status") != "completed"):
            continue
        try:
            stamp = datetime.fromisoformat(str(run["created_at"]).replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError):
            continue
        if stamp.tzinfo is not None:
            candidates.append((stamp.astimezone(UTC), run))
    if not candidates:
        raise ValueError("Fant ingen ferdige produksjonsdiagnoser for main")
    created, selected = max(candidates, key=lambda item: item[0])
    if scheduled:
        age = now.astimezone(UTC) - created
        if not timedelta(0) <= age <= timedelta(hours=3):
            raise ValueError("Siste planlagte produksjonsdiagnose er for gammel: " + created.isoformat())
    return selected

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

FULL_REFRESH_CRON = "35 3 * * *"
FAST_REFRESH_CRON = "*/30 * * * *"


def nightly_due_at(now: datetime) -> datetime:
    """Keep the existing 03:35 UTC schedule, including weekends."""
    current = now.astimezone(UTC)
    return current.replace(hour=3, minute=35, second=0, microsecond=0)


def nightly_is_overdue(started_at: str | None, *, now: datetime) -> bool:
    due = nightly_due_at(now)
    if now < due + timedelta(minutes=55):
        due -= timedelta(days=1)
    if not started_at:
        return True
    try:
        started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return True
    return started < due


async def ensure_nightly_refresh(
    repository: Any, workflow: Any, *, now: datetime
) -> dict:
    due = nightly_due_at(now)
    if now < due:
        return {"status": "SKIPPED", "reason": "not_due"}
    target_date = (due.date() - timedelta(days=1)).isoformat()
    # Avoid repeating a successful native/manual run during migration. A failed
    # or partial run must not suppress the one deterministic recovery instance.
    existing = await repository.first(
        """SELECT id FROM job_runs
           WHERE job_name = 'cloudflare_full_refresh'
             AND status IN ('SUCCESS', 'RUNNING')
             AND json_valid(metadata_json)
             AND json_extract(metadata_json, '$.target_date') = ?
           ORDER BY id DESC LIMIT 1""",
        (target_date,),
    )
    if existing:
        return {
            "status": "SKIPPED",
            "reason": "already_recorded",
            "target_date": target_date,
        }
    instance_id = f"nightly-{target_date}"
    try:
        await workflow.create(
            id=instance_id,
            params={
                "target_date": target_date,
                "trigger": f"worker_cron:{FULL_REFRESH_CRON}",
            },
        )
    except Exception as create_error:
        # Duplicate delivery or an ambiguous create response is safe only when
        # the same instance can actually be read. Never hide an API outage.
        try:
            instance = await workflow.get(instance_id)
            state = await instance.status()
        except Exception:
            raise create_error
        status = state.get("status") if isinstance(state, dict) else state.status
        if status in {"errored", "terminated", "unknown"}:
            raise RuntimeError(
                f"Nightly instance {instance_id}: {status}"
            ) from create_error
        return {"status": "EXISTS", "instance_id": instance_id}
    return {"status": "STARTED", "instance_id": instance_id, "target_date": target_date}

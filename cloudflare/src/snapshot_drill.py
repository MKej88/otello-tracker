from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from workers import WorkflowEntrypoint


def _event_value(event: Any, key: str):
    try:
        return event[key]
    except (KeyError, TypeError):
        return None


def _nested_value(value: Any, key: str):
    if value is None:
        return None
    try:
        return value[key]
    except (KeyError, TypeError):
        return None


def _target_date(event: Any) -> str:
    payload = _event_value(event, "payload")
    explicit = _nested_value(payload, "target_date")
    if explicit:
        return datetime.fromisoformat(str(explicit)).date().isoformat()
    return datetime.now(UTC).date().isoformat()


class R2SnapshotDrillWorkflow(WorkflowEntrypoint):
    """Force one logical D1 snapshot to R2 without mutating production D1 state."""

    async def run(self, event, step):
        from performance_repository import PerformanceD1WriteRepository
        from r2_snapshot import archive_d1_snapshot

        target_date = _target_date(event)

        @step.do(
            "force R2 logical snapshot drill",
            config={"retries": {"limit": 1, "delay": "10 seconds"}, "timeout": "10 minutes"},
        )
        async def snapshot_step():
            repository = PerformanceD1WriteRepository(self.env.DB)
            result = await archive_d1_snapshot(
                repository,
                self.env.SOURCE_ARCHIVE,
                target_date=target_date,
                preflight_status="DRILL_FORCED",
                force=True,
            )
            return {
                **result,
                "drill": True,
                "d1_mode": "READ_ONLY",
                "repository": repository.performance_metrics(),
            }

        return await snapshot_step()

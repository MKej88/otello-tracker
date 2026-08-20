from __future__ import annotations

from datetime import UTC, datetime

from workers import WorkflowEntrypoint


def _event_value(event, key: str):
    try:
        return event[key]
    except (KeyError, TypeError):
        return None


def _nested_value(value, key: str):
    if value is None:
        return None
    try:
        return value[key]
    except (KeyError, TypeError):
        return None


def _target_date(event) -> str:
    payload = _event_value(event, "payload")
    explicit = _nested_value(payload, "target_date")
    if explicit:
        return datetime.fromisoformat(str(explicit)).date().isoformat()

    schedule = _event_value(event, "schedule")
    scheduled_ms = _nested_value(schedule, "scheduledTime")
    if scheduled_ms is not None:
        return datetime.fromtimestamp(float(scheduled_ms) / 1000, tz=UTC).date().isoformat()
    return datetime.now(UTC).date().isoformat()


class ShareholderSnapshotWorkflow(WorkflowEntrypoint):
    """Capture one validated Euronext OMS Top 20 snapshot per daily run."""

    async def run(self, event, step):
        from performance_repository import PerformanceD1WriteRepository
        from shareholder_snapshot_ingestion import refresh_shareholder_snapshot

        target_date = _target_date(event)

        @step.do(
            "capture Euronext Top 20 shareholders",
            config={"retries": {"limit": 1, "delay": "5 minutes"}, "timeout": "2 minutes"},
        )
        async def capture_step():
            repository = PerformanceD1WriteRepository(self.env.DB)
            result = await refresh_shareholder_snapshot(
                repository,
                self.env.BROWSER,
                target_date=target_date,
                archive_bucket=self.env.SOURCE_ARCHIVE,
            )
            return {**result, "repository": repository.performance_metrics()}

        return await capture_step()

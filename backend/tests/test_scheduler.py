from datetime import UTC, datetime

import pytest

from app.db.connection import get_connection
from app.jobs.scheduler import (
    SchedulerConfig,
    load_config,
    persist_fast_cycle,
    run_cycle,
    run_maintenance_if_due,
    run_scheduler,
)


def test_load_config_uses_safe_defaults() -> None:
    config = load_config({"DATABASE_PATH": "/data/test.db"})
    assert config.database_path == "/data/test.db"
    assert config.interval_seconds == 30 * 60
    assert config.full_interval_seconds == 24 * 60 * 60
    assert config.backup_interval_seconds == 24 * 60 * 60
    assert config.backup_dir is None
    assert config.run_on_start is True


def test_load_config_accepts_explicit_intervals_start_policy_and_backup_dir() -> None:
    config = load_config(
        {
            "DATABASE_PATH": "/data/test.db",
            "REFRESH_INTERVAL_MINUTES": "60",
            "FULL_REFRESH_INTERVAL_MINUTES": "720",
            "BACKUP_INTERVAL_MINUTES": "1440",
            "BACKUP_DIR": "/data/snapshots",
            "REFRESH_RUN_ON_START": "false",
        }
    )
    assert config.interval_seconds == 60 * 60
    assert config.full_interval_seconds == 12 * 60 * 60
    assert config.backup_interval_seconds == 24 * 60 * 60
    assert config.backup_dir == "/data/snapshots"
    assert config.run_on_start is False


@pytest.mark.parametrize("value", ["0", "4", "abc"])
def test_load_config_rejects_invalid_or_too_aggressive_fast_interval(value: str) -> None:
    with pytest.raises(ValueError):
        load_config(
            {
                "DATABASE_PATH": "/data/test.db",
                "REFRESH_INTERVAL_MINUTES": value,
            }
        )


@pytest.mark.parametrize("key", ["FULL_REFRESH_INTERVAL_MINUTES", "BACKUP_INTERVAL_MINUTES"])
def test_load_config_rejects_too_aggressive_maintenance_interval(key: str) -> None:
    with pytest.raises(ValueError):
        load_config({"DATABASE_PATH": "/data/test.db", key: "30"})


def test_run_cycle_keeps_degraded_refresh_as_valid_cycle() -> None:
    config = SchedulerConfig("/data/test.db", interval_seconds=1800, run_on_start=True)
    fixed = datetime(2026, 8, 17, 10, 0, tzinfo=UTC)

    def refresh(database_path: str):
        assert database_path == "/data/test.db"
        return {
            "status": "degraded",
            "refresh_mode": "fast",
            "target_date": "2026-08-17",
            "source_errors": [{"step": "newsweb", "error": "temporary"}],
            "dashboard": {"ready": True},
        }

    record = run_cycle(config, refresh_fn=refresh, now_fn=lambda: fixed)
    assert record["event"] == "refresh_complete"
    assert record["refresh_mode"] == "fast"
    assert record["status"] == "degraded"
    assert record["source_error_count"] == 1
    assert record["dashboard_ready"] is True


def test_run_cycle_catches_unexpected_failure_so_scheduler_survives() -> None:
    config = SchedulerConfig("/data/test.db", interval_seconds=1800, run_on_start=True)
    fixed = datetime(2026, 8, 17, 10, 0, tzinfo=UTC)

    def refresh(_database_path: str):
        raise RuntimeError("boom")

    record = run_cycle(config, refresh_fn=refresh, now_fn=lambda: fixed)
    assert record["event"] == "refresh_failed"
    assert record["status"] == "failed"
    assert record["error"] == "boom"


def test_scheduler_can_delay_first_run_and_keeps_start_to_start_cadence(capsys) -> None:
    config = SchedulerConfig("/data/test.db", interval_seconds=600, run_on_start=False)
    sleeps: list[float] = []
    refresh_calls: list[str] = []
    monotonic_values = iter([100.0, 110.0, 200.0])
    fixed = datetime(2026, 8, 17, 10, 0, tzinfo=UTC)

    def refresh(database_path: str):
        refresh_calls.append(database_path)
        return {
            "status": "ok",
            "refresh_mode": "fast",
            "target_date": "2026-08-17",
            "source_errors": [],
            "dashboard": {"ready": True},
        }

    run_scheduler(
        config,
        refresh_fn=refresh,
        sleep_fn=sleeps.append,
        monotonic_fn=lambda: next(monotonic_values),
        now_fn=lambda: fixed,
        max_cycles=2,
    )

    assert refresh_calls == ["/data/test.db", "/data/test.db"]
    assert sleeps == [600.0, 590.0]
    output = capsys.readouterr().out
    assert output.count('"event": "refresh_complete"') == 2


def test_daily_maintenance_runs_once_and_is_persisted(tmp_path) -> None:
    database = str(tmp_path / "scheduler.db")
    backup_dir = str(tmp_path / "backups")
    config = SchedulerConfig(
        database,
        interval_seconds=1800,
        run_on_start=True,
        full_interval_seconds=86400,
        backup_interval_seconds=86400,
        backup_dir=backup_dir,
    )
    fixed = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
    calls: list[str] = []

    def full_refresh(path: str):
        calls.append(f"full:{path}")
        return {
            "status": "ok",
            "target_date": "2026-08-17",
            "source_errors": [],
            "dashboard": {"ready": True},
        }

    def backup(path: str, *, backup_dir: str | None = None):
        calls.append(f"backup:{path}:{backup_dir}")
        return {
            "status": "ok",
            "backup_path": f"{backup_dir}/otello.db",
            "size_bytes": 123,
            "integrity_check": "ok",
        }

    first = run_maintenance_if_due(
        config,
        full_refresh_fn=full_refresh,
        backup_fn=backup,
        now_fn=lambda: fixed,
    )
    second = run_maintenance_if_due(
        config,
        full_refresh_fn=full_refresh,
        backup_fn=backup,
        now_fn=lambda: fixed,
    )

    assert [item["job_name"] for item in first] == ["full_refresh", "database_backup"]
    assert second == []
    assert calls == [
        f"full:{database}",
        f"backup:{database}:{backup_dir}",
    ]

    with get_connection(database) as connection:
        rows = connection.execute(
            "SELECT job_name, status FROM job_runs ORDER BY id"
        ).fetchall()
    assert [(row["job_name"], row["status"]) for row in rows] == [
        ("full_refresh", "SUCCESS"),
        ("database_backup", "SUCCESS"),
    ]


def test_degraded_full_refresh_counts_as_completed_maintenance_window(tmp_path) -> None:
    database = str(tmp_path / "scheduler-partial.db")
    config = SchedulerConfig(database, 1800, True, full_interval_seconds=86400, backup_interval_seconds=86400)
    fixed = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
    calls = 0

    def full_refresh(_path: str):
        nonlocal calls
        calls += 1
        return {
            "status": "degraded",
            "target_date": "2026-08-17",
            "source_errors": [{"step": "ecb", "error": "temporary"}],
            "dashboard": {"ready": True},
        }

    def backup(_path: str, *, backup_dir: str | None = None):
        return {"status": "ok", "backup_path": "x", "size_bytes": 1, "integrity_check": "ok"}

    first = run_maintenance_if_due(
        config, full_refresh_fn=full_refresh, backup_fn=backup, now_fn=lambda: fixed
    )
    second = run_maintenance_if_due(
        config, full_refresh_fn=full_refresh, backup_fn=backup, now_fn=lambda: fixed
    )

    assert first[0]["status"] == "partial"
    assert second == []
    assert calls == 1


def test_persist_fast_cycle_records_compact_job_state(tmp_path) -> None:
    database = str(tmp_path / "fast.db")
    persist_fast_cycle(
        database,
        {
            "refresh_mode": "fast",
            "started_at": "2026-08-17T12:00:00+00:00",
            "finished_at": "2026-08-17T12:00:03+00:00",
            "status": "degraded",
            "target_date": "2026-08-17",
            "source_error_count": 1,
            "dashboard_ready": True,
        },
    )
    with get_connection(database) as connection:
        row = connection.execute(
            "SELECT job_name, status, metadata_json FROM job_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert row["job_name"] == "fast_refresh"
    assert row["status"] == "PARTIAL"
    assert '"source_error_count": 1' in row["metadata_json"]

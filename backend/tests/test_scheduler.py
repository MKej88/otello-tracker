from datetime import UTC, datetime

import pytest

from app.jobs.scheduler import SchedulerConfig, load_config, run_cycle, run_scheduler


def test_load_config_uses_safe_defaults() -> None:
    config = load_config({"DATABASE_PATH": "/data/test.db"})
    assert config.database_path == "/data/test.db"
    assert config.interval_seconds == 30 * 60
    assert config.run_on_start is True


def test_load_config_accepts_explicit_interval_and_start_policy() -> None:
    config = load_config(
        {
            "DATABASE_PATH": "/data/test.db",
            "REFRESH_INTERVAL_MINUTES": "60",
            "REFRESH_RUN_ON_START": "false",
        }
    )
    assert config.interval_seconds == 60 * 60
    assert config.run_on_start is False


@pytest.mark.parametrize("value", ["0", "4", "abc"])
def test_load_config_rejects_invalid_or_too_aggressive_interval(value: str) -> None:
    with pytest.raises(ValueError):
        load_config(
            {
                "DATABASE_PATH": "/data/test.db",
                "REFRESH_INTERVAL_MINUTES": value,
            }
        )


def test_run_cycle_keeps_degraded_refresh_as_valid_cycle() -> None:
    config = SchedulerConfig("/data/test.db", interval_seconds=1800, run_on_start=True)
    fixed = datetime(2026, 8, 17, 10, 0, tzinfo=UTC)

    def refresh(database_path: str):
        assert database_path == "/data/test.db"
        return {
            "status": "degraded",
            "target_date": "2026-08-17",
            "source_errors": [{"step": "ecb", "error": "temporary"}],
            "dashboard": {"ready": True},
        }

    record = run_cycle(config, refresh_fn=refresh, now_fn=lambda: fixed)
    assert record["event"] == "refresh_complete"
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

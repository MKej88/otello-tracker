from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable, Mapping

from app.jobs.refresh_dashboard import run_refresh
from app.settings import settings

DEFAULT_INTERVAL_MINUTES = 30
MIN_INTERVAL_MINUTES = 5


@dataclass(frozen=True)
class SchedulerConfig:
    database_path: str
    interval_seconds: int
    run_on_start: bool


def _parse_bool(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Ugyldig boolsk verdi: {value!r}")


def load_config(environ: Mapping[str, str] | None = None) -> SchedulerConfig:
    env = environ or os.environ
    raw_interval = env.get("REFRESH_INTERVAL_MINUTES", str(DEFAULT_INTERVAL_MINUTES)).strip()
    try:
        interval_minutes = int(raw_interval)
    except ValueError as exc:
        raise ValueError("REFRESH_INTERVAL_MINUTES må være et heltall") from exc
    if interval_minutes < MIN_INTERVAL_MINUTES:
        raise ValueError(
            f"REFRESH_INTERVAL_MINUTES må være minst {MIN_INTERVAL_MINUTES} minutter"
        )

    database_path = env.get("DATABASE_PATH", settings.database_path).strip()
    if not database_path:
        raise ValueError("DATABASE_PATH kan ikke være tom")

    return SchedulerConfig(
        database_path=database_path,
        interval_seconds=interval_minutes * 60,
        run_on_start=_parse_bool(env.get("REFRESH_RUN_ON_START"), default=True),
    )


def run_cycle(
    config: SchedulerConfig,
    *,
    refresh_fn: Callable[..., dict[str, Any]] = run_refresh,
    now_fn: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    clock = now_fn or (lambda: datetime.now(UTC))
    started_at = clock()
    try:
        result = refresh_fn(config.database_path)
        return {
            "event": "refresh_complete",
            "started_at": started_at.isoformat(),
            "finished_at": clock().isoformat(),
            "status": result.get("status", "unknown"),
            "target_date": result.get("target_date"),
            "source_error_count": len(result.get("source_errors") or []),
            "dashboard_ready": bool((result.get("dashboard") or {}).get("ready")),
        }
    except Exception as exc:  # keep the production scheduler alive on unexpected failures
        return {
            "event": "refresh_failed",
            "started_at": started_at.isoformat(),
            "finished_at": clock().isoformat(),
            "status": "failed",
            "error": str(exc),
        }


def run_scheduler(
    config: SchedulerConfig,
    *,
    refresh_fn: Callable[..., dict[str, Any]] = run_refresh,
    sleep_fn: Callable[[float], None] = time.sleep,
    monotonic_fn: Callable[[], float] = time.monotonic,
    now_fn: Callable[[], datetime] | None = None,
    max_cycles: int | None = None,
) -> None:
    if max_cycles is not None and max_cycles < 0:
        raise ValueError("max_cycles kan ikke være negativ")
    if max_cycles == 0:
        return

    if not config.run_on_start:
        sleep_fn(float(config.interval_seconds))

    cycles = 0
    while max_cycles is None or cycles < max_cycles:
        cycle_started = monotonic_fn()
        record = run_cycle(config, refresh_fn=refresh_fn, now_fn=now_fn)
        print(json.dumps(record, ensure_ascii=False, default=str), flush=True)
        cycles += 1

        if max_cycles is not None and cycles >= max_cycles:
            break

        elapsed = max(0.0, monotonic_fn() - cycle_started)
        sleep_seconds = max(1.0, float(config.interval_seconds) - elapsed)
        sleep_fn(sleep_seconds)


def main() -> None:
    config = load_config()
    print(
        json.dumps(
            {
                "event": "scheduler_started",
                "database_path": config.database_path,
                "interval_seconds": config.interval_seconds,
                "run_on_start": config.run_on_start,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    run_scheduler(config)


if __name__ == "__main__":
    main()

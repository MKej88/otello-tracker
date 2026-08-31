from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable, Mapping

from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.jobs.backup_database import backup_database
from app.jobs.fast_refresh import run_fast_refresh
from app.jobs.refresh_dashboard_v2 import run_refresh as run_full_refresh
from app.settings import settings

DEFAULT_INTERVAL_MINUTES = 30
MIN_INTERVAL_MINUTES = 5
DEFAULT_FULL_INTERVAL_MINUTES = 24 * 60
DEFAULT_BACKUP_INTERVAL_MINUTES = 24 * 60
MIN_MAINTENANCE_INTERVAL_MINUTES = 60


@dataclass(frozen=True)
class SchedulerConfig:
    database_path: str
    interval_seconds: int
    run_on_start: bool
    full_interval_seconds: int = DEFAULT_FULL_INTERVAL_MINUTES * 60
    backup_interval_seconds: int = DEFAULT_BACKUP_INTERVAL_MINUTES * 60
    backup_dir: str | None = None


def _parse_bool(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Ugyldig boolsk verdi: {value!r}")


def _parse_minutes(
    env: Mapping[str, str],
    key: str,
    default: int,
    minimum: int,
) -> int:
    raw = env.get(key, str(default)).strip()
    try:
        minutes = int(raw)
    except ValueError as exc:
        raise ValueError(f"{key} må være et heltall") from exc
    if minutes < minimum:
        raise ValueError(f"{key} må være minst {minimum} minutter")
    return minutes


def load_config(environ: Mapping[str, str] | None = None) -> SchedulerConfig:
    env = os.environ if environ is None else environ
    interval_minutes = _parse_minutes(
        env, "REFRESH_INTERVAL_MINUTES", DEFAULT_INTERVAL_MINUTES, MIN_INTERVAL_MINUTES
    )
    full_interval_minutes = _parse_minutes(
        env,
        "FULL_REFRESH_INTERVAL_MINUTES",
        DEFAULT_FULL_INTERVAL_MINUTES,
        MIN_MAINTENANCE_INTERVAL_MINUTES,
    )
    backup_interval_minutes = _parse_minutes(
        env,
        "BACKUP_INTERVAL_MINUTES",
        DEFAULT_BACKUP_INTERVAL_MINUTES,
        MIN_MAINTENANCE_INTERVAL_MINUTES,
    )

    database_path = env.get("DATABASE_PATH", settings.database_path).strip()
    if not database_path:
        raise ValueError("DATABASE_PATH kan ikke være tom")
    backup_dir = env.get("BACKUP_DIR", "").strip() or None

    return SchedulerConfig(
        database_path=database_path,
        interval_seconds=interval_minutes * 60,
        run_on_start=_parse_bool(env.get("REFRESH_RUN_ON_START"), default=True),
        full_interval_seconds=full_interval_minutes * 60,
        backup_interval_seconds=backup_interval_minutes * 60,
        backup_dir=backup_dir,
    )


def run_cycle(
    config: SchedulerConfig,
    *,
    refresh_fn: Callable[..., dict[str, Any]] = run_fast_refresh,
    now_fn: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    clock = now_fn or (lambda: datetime.now(UTC))
    started_at = clock()
    try:
        result = refresh_fn(config.database_path)
        return {
            "event": "refresh_complete",
            "refresh_mode": result.get("refresh_mode", "fast"),
            "started_at": started_at.isoformat(),
            "finished_at": clock().isoformat(),
            "status": result.get("status", "unknown"),
            "target_date": result.get("target_date"),
            "source_error_count": len(result.get("source_errors") or []),
            "dashboard_ready": bool((result.get("dashboard") or {}).get("ready")),
        }
    except (
        Exception
    ) as exc:  # keep the production scheduler alive on unexpected failures
        return {
            "event": "refresh_failed",
            "refresh_mode": "fast",
            "started_at": started_at.isoformat(),
            "finished_at": clock().isoformat(),
            "status": "failed",
            "error": str(exc),
        }


def _parse_timestamp(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _job_due(
    database_path: str,
    job_name: str,
    interval_seconds: int,
    now: datetime,
) -> bool:
    init_database(database_path)
    with get_connection(database_path) as connection:
        row = connection.execute(
            """
            SELECT finished_at
            FROM job_runs
            WHERE job_name=? AND status IN ('SUCCESS','PARTIAL') AND finished_at IS NOT NULL
            ORDER BY finished_at DESC, id DESC LIMIT 1
            """,
            (job_name,),
        ).fetchone()
    if row is None:
        return True
    return (
        now.astimezone(UTC) - _parse_timestamp(row["finished_at"])
    ).total_seconds() >= interval_seconds


def _job_result_status(result: dict[str, Any]) -> str:
    status = str(result.get("status", "")).lower()
    if status in {"ok", "ready", "success"}:
        return "SUCCESS"
    return "PARTIAL"


def _job_metadata(result: dict[str, Any]) -> dict[str, Any]:
    dashboard = result.get("dashboard") or {}
    return {
        "result_status": result.get("status"),
        "target_date": result.get("target_date"),
        "source_error_count": len(result.get("source_errors") or []),
        "dashboard_ready": bool(dashboard.get("ready")),
        "backup_path": result.get("backup_path"),
        "size_bytes": result.get("size_bytes"),
        "integrity_check": result.get("integrity_check"),
    }


def _run_managed_job(
    database_path: str,
    job_name: str,
    fn: Callable[[], dict[str, Any]],
    *,
    interval_seconds: int,
    now_fn: Callable[[], datetime] | None = None,
) -> dict[str, Any] | None:
    clock = now_fn or (lambda: datetime.now(UTC))
    init_database(database_path)
    started = clock()
    with get_connection(database_path) as connection:
        # Kontroll og reservasjon må skje i samme skrivetransaksjon. Ellers kan
        # to planleggere se at jobben er klar og starte den samtidig.
        connection.execute("BEGIN IMMEDIATE")
        latest_completed = connection.execute(
            """
            SELECT finished_at
            FROM job_runs
            WHERE job_name=? AND status IN ('SUCCESS','PARTIAL')
                AND finished_at IS NOT NULL
            ORDER BY finished_at DESC, id DESC LIMIT 1
            """,
            (job_name,),
        ).fetchone()
        if (
            latest_completed is not None
            and (
                started.astimezone(UTC)
                - _parse_timestamp(latest_completed["finished_at"])
            ).total_seconds()
            < interval_seconds
        ):
            connection.rollback()
            return None

        latest_running = connection.execute(
            """
            SELECT started_at
            FROM job_runs
            WHERE job_name=? AND status='RUNNING'
            ORDER BY started_at DESC, id DESC LIMIT 1
            """,
            (job_name,),
        ).fetchone()
        if (
            latest_running is not None
            and (
                started.astimezone(UTC) - _parse_timestamp(latest_running["started_at"])
            ).total_seconds()
            < interval_seconds
        ):
            connection.rollback()
            return None

        cursor = connection.execute(
            """
            INSERT INTO job_runs(job_name, started_at, status, metadata_json)
            VALUES (?, ?, 'RUNNING', '{}')
            """,
            (job_name, started.isoformat()),
        )
        job_id = int(cursor.lastrowid)
        connection.commit()

    try:
        result = fn()
        finished = clock()
        status = _job_result_status(result)
        metadata = _job_metadata(result)
        with get_connection(database_path) as connection:
            connection.execute(
                """
                UPDATE job_runs
                SET finished_at=?, status=?, metadata_json=?
                WHERE id=?
                """,
                (
                    finished.isoformat(),
                    status,
                    json.dumps(metadata, ensure_ascii=False),
                    job_id,
                ),
            )
            connection.commit()
        return {
            "event": "maintenance_complete",
            "job_name": job_name,
            "status": status.lower(),
            "started_at": started.isoformat(),
            "finished_at": finished.isoformat(),
            **metadata,
        }
    except Exception as exc:
        finished = clock()
        with get_connection(database_path) as connection:
            connection.execute(
                """
                UPDATE job_runs
                SET finished_at=?, status='FAILED', error_message=?
                WHERE id=?
                """,
                (finished.isoformat(), str(exc), job_id),
            )
            connection.commit()
        return {
            "event": "maintenance_failed",
            "job_name": job_name,
            "status": "failed",
            "started_at": started.isoformat(),
            "finished_at": finished.isoformat(),
            "error": str(exc),
        }


def persist_fast_cycle(database_path: str, record: dict[str, Any]) -> None:
    """Persist the compact fast-cycle result without storing the full refresh payload."""
    init_database(database_path)
    if record.get("status") == "failed":
        status = "FAILED"
    elif record.get("status") == "ok":
        status = "SUCCESS"
    else:
        status = "PARTIAL"
    metadata = {
        "refresh_mode": record.get("refresh_mode"),
        "target_date": record.get("target_date"),
        "source_error_count": record.get("source_error_count"),
        "dashboard_ready": record.get("dashboard_ready"),
    }
    with get_connection(database_path) as connection:
        connection.execute(
            """
            INSERT INTO job_runs(
                job_name, started_at, finished_at, status, error_message, metadata_json
            ) VALUES ('fast_refresh', ?, ?, ?, ?, ?)
            """,
            (
                record.get("started_at"),
                record.get("finished_at"),
                status,
                record.get("error"),
                json.dumps(metadata, ensure_ascii=False),
            ),
        )
        connection.commit()


def run_maintenance_if_due(
    config: SchedulerConfig,
    *,
    full_refresh_fn: Callable[[str], dict[str, Any]] = run_full_refresh,
    backup_fn: Callable[..., dict[str, Any]] = backup_database,
    now_fn: Callable[[], datetime] | None = None,
) -> list[dict[str, Any]]:
    clock = now_fn or (lambda: datetime.now(UTC))
    now = clock()
    records: list[dict[str, Any]] = []

    if _job_due(
        config.database_path, "full_refresh", config.full_interval_seconds, now
    ):
        record = _run_managed_job(
            config.database_path,
            "full_refresh",
            lambda: full_refresh_fn(config.database_path),
            interval_seconds=config.full_interval_seconds,
            now_fn=clock,
        )
        if record is not None:
            records.append(record)

    if _job_due(
        config.database_path, "database_backup", config.backup_interval_seconds, now
    ):
        record = _run_managed_job(
            config.database_path,
            "database_backup",
            lambda: backup_fn(config.database_path, backup_dir=config.backup_dir),
            interval_seconds=config.backup_interval_seconds,
            now_fn=clock,
        )
        if record is not None:
            records.append(record)
    return records


def run_scheduler(
    config: SchedulerConfig,
    *,
    refresh_fn: Callable[..., dict[str, Any]] = run_fast_refresh,
    sleep_fn: Callable[[float], None] = time.sleep,
    monotonic_fn: Callable[[], float] = time.monotonic,
    now_fn: Callable[[], datetime] | None = None,
    max_cycles: int | None = None,
    maintenance_fn: Callable[[SchedulerConfig], list[dict[str, Any]]] | None = None,
    persist_fn: Callable[[str, dict[str, Any]], None] | None = None,
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
        if persist_fn is not None:
            try:
                persist_fn(config.database_path, record)
            except Exception as exc:
                print(
                    json.dumps(
                        {"event": "job_persistence_failed", "error": str(exc)},
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
        if maintenance_fn is not None:
            try:
                for maintenance_record in maintenance_fn(config):
                    print(
                        json.dumps(maintenance_record, ensure_ascii=False, default=str),
                        flush=True,
                    )
            except Exception as exc:
                print(
                    json.dumps(
                        {"event": "maintenance_dispatch_failed", "error": str(exc)},
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
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
                "fast_interval_seconds": config.interval_seconds,
                "full_interval_seconds": config.full_interval_seconds,
                "backup_interval_seconds": config.backup_interval_seconds,
                "backup_dir": config.backup_dir,
                "run_on_start": config.run_on_start,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    run_scheduler(
        config,
        maintenance_fn=run_maintenance_if_due,
        persist_fn=persist_fast_cycle,
    )


if __name__ == "__main__":
    main()

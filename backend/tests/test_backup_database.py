import sqlite3
from datetime import UTC, datetime

import pytest

from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.jobs.backup_database import backup_database


def test_backup_database_creates_consistent_verified_snapshot(tmp_path) -> None:
    database = str(tmp_path / "otello.db")
    backup_dir = tmp_path / "backups"
    init_database(database)
    with get_connection(database) as connection:
        connection.execute(
            "INSERT INTO job_runs(job_name, started_at, status) VALUES ('seed', '2026-08-17T10:00:00+00:00', 'SUCCESS')"
        )
        connection.commit()

    result = backup_database(
        database,
        backup_dir=str(backup_dir),
        now=datetime(2026, 8, 17, 12, 0, tzinfo=UTC),
    )

    assert result["status"] == "ok"
    assert result["integrity_check"] == "ok"
    assert result["size_bytes"] > 0
    assert result["backup_path"].endswith("otello-20260817T120000Z.db")

    backup = sqlite3.connect(result["backup_path"])
    try:
        assert backup.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert backup.execute("SELECT COUNT(*) FROM job_runs").fetchone()[0] == 1
    finally:
        backup.close()


def test_backup_rejects_missing_or_non_filesystem_database(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        backup_database(str(tmp_path / "missing.db"))
    with pytest.raises(ValueError):
        backup_database(":memory:")

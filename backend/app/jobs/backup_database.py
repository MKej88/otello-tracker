from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.db.connection import connect
from app.settings import settings


def backup_database(
    database_path: str,
    *,
    backup_dir: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Create a transactionally consistent SQLite snapshot and verify the snapshot."""
    if database_path == ":memory:" or database_path.startswith("file:"):
        raise ValueError("Production backup requires a filesystem database path")

    source_path = Path(database_path).expanduser().resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"Database does not exist: {source_path}")

    destination_dir = (
        Path(backup_dir).expanduser().resolve()
        if backup_dir
        else source_path.parent / "backups"
    )
    destination_dir.mkdir(parents=True, exist_ok=True)

    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    current = current.astimezone(UTC)
    timestamp = current.strftime("%Y%m%dT%H%M%SZ")
    final_path = destination_dir / f"otello-{timestamp}.db"
    if final_path.exists():
        raise FileExistsError(f"Backup already exists: {final_path}")

    source = connect(str(source_path))
    target = sqlite3.connect(str(final_path))
    try:
        source.backup(target)
        target.commit()
        integrity = target.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"Backup integrity_check failed: {integrity}")
    except Exception:
        target.close()
        source.close()
        if final_path.exists():
            final_path.unlink()
        raise
    else:
        target.close()
        source.close()

    return {
        "status": "ok",
        "database": str(source_path),
        "backup_path": str(final_path),
        "size_bytes": final_path.stat().st_size,
        "integrity_check": "ok",
        "created_at": current.isoformat(),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create and verify an Otello SQLite backup")
    parser.add_argument("--database", default=settings.database_path)
    parser.add_argument("--backup-dir", default=None)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    result = backup_database(args.database, backup_dir=args.backup_dir)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()

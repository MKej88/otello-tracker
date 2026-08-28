from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.settings import settings


def _prepare_database_path(database_path: str) -> str:
    if database_path == ":memory:" or database_path.startswith("file:"):
        return database_path

    expanded_path = Path(database_path).expanduser()
    expanded_path.resolve().parent.mkdir(parents=True, exist_ok=True)
    return str(expanded_path)


def connect(database_path: str | None = None) -> sqlite3.Connection:
    configured_path = database_path or settings.database_path
    path = _prepare_database_path(configured_path)

    connection = sqlite3.connect(
        path,
        timeout=10.0,
        detect_types=sqlite3.PARSE_DECLTYPES,
        uri=path.startswith("file:"),
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")

    if path != ":memory:" and not path.startswith("file:"):
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")

    return connection


@contextmanager
def get_connection(database_path: str | None = None) -> Iterator[sqlite3.Connection]:
    connection = connect(database_path)
    try:
        yield connection
    finally:
        connection.close()

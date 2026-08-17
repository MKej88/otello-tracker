from __future__ import annotations

from app.db.connection import get_connection


def get_runtime_state(key: str, database_path: str | None = None) -> str | None:
    with get_connection(database_path) as connection:
        row = connection.execute(
            "SELECT value FROM runtime_state WHERE key = ?",
            (key,),
        ).fetchone()
    return str(row["value"]) if row is not None else None


def set_runtime_state(key: str, value: str, database_path: str | None = None) -> None:
    with get_connection(database_path) as connection:
        connection.execute(
            """
            INSERT INTO runtime_state(key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            """,
            (key, value),
        )
        connection.commit()

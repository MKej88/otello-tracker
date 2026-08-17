from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def _to_python(value: Any) -> Any:
    """Convert Worker/Pyodide JS proxy values to ordinary Python containers."""
    converter = getattr(value, "to_py", None)
    if callable(converter):
        try:
            value = converter()
        except (TypeError, RuntimeError):
            pass

    if isinstance(value, Mapping):
        return {str(key): _to_python(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_to_python(item) for item in value]

    items = getattr(value, "items", None)
    if callable(items):
        try:
            return {str(key): _to_python(item) for key, item in items()}
        except (TypeError, RuntimeError):
            pass
    return value


class D1Repository:
    """Minimal read-only data-access layer for dashboard API queries.

    Phase 15.3 deliberately exposes only SELECT-style helpers. Scheduled ingestion and
    write paths are introduced separately in Phase 15.4/15.5 so the API migration cannot
    accidentally change the authoritative financial data.
    """

    def __init__(self, database: Any):
        self.database = database

    async def all(self, sql: str, parameters: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        statement = self.database.prepare(sql)
        if parameters:
            statement = statement.bind(*parameters)
        result = await statement.all()
        rows = _to_python(getattr(result, "results", []))
        if rows is None:
            return []
        if isinstance(rows, Mapping):
            rows = [rows]
        return [dict(row) for row in rows]

    async def first(
        self,
        sql: str,
        parameters: tuple[Any, ...] = (),
    ) -> dict[str, Any] | None:
        rows = await self.all(sql, parameters)
        return rows[0] if rows else None

from __future__ import annotations

from contextlib import nullcontext
from datetime import date, timedelta

import app.estimated_nav_history as history_module


class _Cursor:
    def __init__(self, *, one=None, rows=None) -> None:
        self._one = one
        self._rows = rows or []

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._rows


class _CountingConnection:
    def __init__(self, days: list[str]) -> None:
        self.days = days
        self.snapshot_queries = 0

    def execute(self, query: str, params=()):
        normalized = " ".join(query.split())
        if "SELECT MAX(substr(as_of_at,1,10)) AS max_date" in normalized:
            return _Cursor(one={"max_date": self.days[-1]})
        if "SELECT DISTINCT substr(as_of_at,1,10) AS date" in normalized:
            return _Cursor(rows=[{"date": day} for day in self.days])
        if "SELECT MAX(substr(as_of_at,1,10)) AS date" in normalized:
            return _Cursor(one={"date": self.days[0]})
        if "WITH ranked AS" in normalized:
            self.snapshot_queries += 1
            return _Cursor(rows=[{"date": day} for day in params[1:]])
        raise AssertionError(f"Uventet SQL: {normalized}")


def test_history_batches_snapshot_reads(monkeypatch) -> None:
    start = date(2026, 6, 1)
    days = [(start + timedelta(days=offset)).isoformat() for offset in range(72)]
    connection = _CountingConnection(days)
    received_rows = 0

    def fake_estimated_point(
        _connection, day: str, _database_path, *, snapshot_row=None
    ):
        nonlocal received_rows
        assert snapshot_row == {"date": day}
        received_rows += 1
        return {
            "ready": True,
            "date": day,
            "nav_per_share": 10.0,
            "otec_price": 5.0,
            "discount_pct": 50.0,
        }

    monkeypatch.setattr(
        history_module,
        "get_connection",
        lambda _database_path=None: nullcontext(connection),
    )
    monkeypatch.setattr(history_module, "_estimated_point", fake_estimated_point)
    monkeypatch.setattr(history_module, "_change", lambda *_args: {"ready": True})

    result = history_module.estimated_nav_history(days=3650)

    assert result["ready"] is True
    assert received_rows == 72
    assert connection.snapshot_queries == 1

from __future__ import annotations

from datetime import date, timedelta

import pytest

import app.estimated_nav_history as history_module


class _Cursor:
    def __init__(self, *, one=None, rows=None) -> None:
        self._one = one
        self._rows = rows or []

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._rows


class _FakeConnection:
    def __init__(self, current_day: str) -> None:
        self.current_day = current_day
        self.seen_requested_start: str | None = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def execute(self, query: str, params=()):
        normalized = " ".join(query.split())

        if "SELECT MAX(substr(as_of_at,1,10)) AS max_date" in normalized:
            return _Cursor(one={"max_date": self.current_day})

        if "SELECT DISTINCT substr(as_of_at,1,10) AS date" in normalized:
            requested_start = str(params[1])
            current_date = str(params[2])
            self.seen_requested_start = requested_start
            return _Cursor(
                rows=[
                    {"date": requested_start},
                    {"date": current_date},
                ]
            )

        if "SELECT MAX(substr(as_of_at,1,10)) AS date" in normalized:
            requested_start = str(params[1])
            return _Cursor(one={"date": requested_start})

        if "WITH ranked AS" in normalized:
            return _Cursor(rows=[{"date": str(day)} for day in params[1:]])

        raise AssertionError(f"Unexpected SQL in rolling-window test: {normalized}")


def _estimated_point(_connection, day: str, _database_path, *, snapshot_row=None):
    assert snapshot_row == {"date": day}
    return {
        "ready": True,
        "date": day,
        "nav_per_share": 10.0,
        "otec_price": 5.0,
        "discount_pct": 50.0,
    }


def _change(start, current, requested_start: str, _database_path):
    return {
        "ready": True,
        "requested_start": requested_start,
        "resolved_start": start["date"],
        "current_date": current["date"],
    }


@pytest.mark.parametrize(
    ("current_day", "expected_start"),
    [
        ("2026-08-30", "2023-08-31"),
        ("2026-08-31", "2023-09-01"),
        ("2026-09-01", "2023-09-02"),
        ("2026-12-31", "2024-01-01"),
        ("2028-03-01", "2025-03-02"),
    ],
)
def test_three_year_window_rolls_from_latest_full_nav_date(
    monkeypatch: pytest.MonkeyPatch,
    current_day: str,
    expected_start: str,
) -> None:
    """3Y must keep rolling; it must never be pinned to the 2026 regression dates."""
    connection = _FakeConnection(current_day)
    monkeypatch.setattr(
        history_module,
        "get_connection",
        lambda _database_path=None: connection,
    )
    monkeypatch.setattr(history_module, "_estimated_point", _estimated_point)
    monkeypatch.setattr(history_module, "_change", _change)

    result = history_module.estimated_nav_history(days=1095)

    assert result["ready"] is True
    assert result["requested_start"] == expected_start
    assert connection.seen_requested_start == expected_start
    assert result["from"] == expected_start
    assert result["to"] == current_day
    assert result["current"]["date"] == current_day
    assert result["change"]["requested_start"] == expected_start
    assert result["change"]["resolved_start"] == expected_start
    assert result["change"]["current_date"] == current_day
    assert (
        date.fromisoformat(current_day) - date.fromisoformat(result["requested_start"])
        == timedelta(days=1095)
    )

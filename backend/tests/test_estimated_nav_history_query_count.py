from __future__ import annotations

import json
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


class _MaterializedConnection:
    def __init__(self, days: list[str]) -> None:
        self.days = days
        self.history_queries = 0

    def execute(self, query: str, _params=()):
        normalized = " ".join(query.split())
        if "SELECT MAX(date) AS max_date" in normalized:
            return _Cursor(one={"max_date": self.days[-1]})
        if "date>=? AND date<=?" in normalized:
            self.history_queries += 1
            return _Cursor(rows=[_row(day) for day in self.days])
        if "date<=? ORDER BY date DESC LIMIT 1" in normalized:
            return _Cursor(one=_row(self.days[0]))
        raise AssertionError(f"Uventet SQL: {normalized}")


def _row(day: str) -> dict:
    return {
        "date": day,
        "nav_total_mnok": 100.0,
        "nav_per_share_nok": 10.0,
        "otec_price_nok": 5.0,
        "discount_pct": 50.0,
        "shares_outstanding": 10,
        "accounting_nav_per_share_nok": 9.0,
        "composition_json": json.dumps([]),
        "reconciliation_residual_mnok": 0.0,
    }


def test_history_reads_one_materialized_series_without_reconstruction(
    monkeypatch,
) -> None:
    start = date(2026, 1, 1)
    days = [(start + timedelta(days=offset)).isoformat() for offset in range(250)]
    connection = _MaterializedConnection(days)

    monkeypatch.setattr(
        history_module, "get_connection", lambda _path=None: nullcontext(connection)
    )
    monkeypatch.setattr(
        history_module,
        "_estimated_point",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError(
                "request-pathen skal ikke rekonstruere historiske NAV-punkter"
            )
        ),
    )
    monkeypatch.setattr(history_module, "_change", lambda *_args: {"ready": True})

    result = history_module.estimated_nav_history(days=3650)

    assert result["ready"] is True
    assert connection.history_queries == 1
    assert result["observation_count"] == 250
    assert result["chart_point_count"] == 72
    assert result["points"][0]["date"] == days[0]
    assert result["points"][-1]["date"] == days[-1]

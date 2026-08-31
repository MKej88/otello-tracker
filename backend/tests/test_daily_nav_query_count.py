from __future__ import annotations

from datetime import date, timedelta

from app.nav.daily_nav import _load_daily_reference_data


class _Cursor:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[dict[str, object]]:
        return self._rows


class _CountingConnection:
    def __init__(self) -> None:
        self.queries = 0

    def execute(self, query: str, _params=()) -> _Cursor:
        self.queries += 1
        if "FROM bemobi_holdings" in query:
            return _Cursor(
                [
                    {
                        "id": 1,
                        "shares": 10,
                        "ownership_pct": "1",
                        "effective_from": "2024-01-01",
                        "effective_to": None,
                    }
                ]
            )
        if "FROM otello_share_counts" in query:
            return _Cursor(
                [
                    {
                        "id": 2,
                        "effective_from": "2024-01-01",
                        "total_shares": 100,
                        "treasury_shares": 10,
                        "outstanding_shares": 90,
                    }
                ]
            )
        if "FROM buybacks" in query:
            return _Cursor(
                [
                    {
                        "id": 3,
                        "trade_date": "2024-01-02",
                        "cumulative_program_shares": 5,
                        "max_shares": 20,
                    }
                ]
            )
        raise AssertionError(f"Uventet SQL: {query}")


def test_daily_nav_batches_slowly_changing_reference_reads() -> None:
    start = date(2024, 1, 1)
    dates = [(start + timedelta(days=offset)).isoformat() for offset in range(1_000)]
    connection = _CountingConnection()

    result = _load_daily_reference_data(connection, dates)

    assert len(result) == 1_000
    assert result[dates[0]]["holding"]["id"] == 1
    assert result[dates[0]]["share_count"]["id"] == 2
    assert result[dates[0]]["latest_buyback"] is None
    assert result[dates[1]]["latest_buyback"]["id"] == 3
    assert connection.queries == 3

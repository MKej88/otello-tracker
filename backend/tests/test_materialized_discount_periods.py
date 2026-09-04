from __future__ import annotations

from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app import materialized_discount_history as cache


def _seed_history(database_path: str, day: str) -> None:
    init_database(database_path)
    with get_connection(database_path) as connection:
        connection.execute(
            """INSERT INTO estimated_nav_history_points(
                   date, calculation_version, nav_total_mnok, nav_per_share_nok,
                   otec_price_nok, discount_pct, shares_outstanding,
                   accounting_nav_per_share_nok, composition_json,
                   reconciliation_residual_mnok, quality, calculated_at
               ) VALUES (?, ?, 100.0, 10.0, 5.0, 50.0, 10000000,
                         9.5, '[]', 0.0, 'VALID', '2026-09-04T01:00:00Z')
               ON CONFLICT(date, calculation_version) DO UPDATE SET
                   calculated_at=excluded.calculated_at""",
            (day, cache.ESTIMATED_NAV_CALCULATION_VERSION),
        )
        connection.commit()


def test_materializes_all_investor_periods_and_serves_bundle(tmp_path, monkeypatch) -> None:
    database_path = str(tmp_path / "period-cache.db")
    _seed_history(database_path, "2026-09-03")
    calls: list[tuple[int, int, bool]] = []

    def fake_discount_history(
        database_path_arg=None,
        *,
        days: int,
        max_points: int,
        year_to_date: bool,
    ):
        assert database_path_arg == database_path
        calls.append((days, max_points, year_to_date))
        return {
            "ready": True,
            "estimated": {
                "ready": True,
                "to": "2026-09-03",
                "current": {"date": "2026-09-03", "nav_per_share": 10.0},
                "change": {
                    "ready": True,
                    "current_date": "2026-09-03",
                    "drivers": [{"key": "bemobi_price", "per_share_nok": 1.0}],
                },
            },
        }

    monkeypatch.setattr(cache, "discount_history", fake_discount_history)
    result = cache.materialize_discount_periods(database_path)

    assert result["status"] == "ok"
    assert result["written"] == 6
    assert result["periods"] == list(cache.PERIOD_KEYS)
    assert len(calls) == 6
    assert all(max_points == 72 for _, max_points, _ in calls)
    assert any(year_to_date for _, _, year_to_date in calls)

    def should_not_recalculate(*args, **kwargs):
        raise AssertionError("fresh materialized period should avoid live calculation")

    monkeypatch.setattr(cache, "discount_history", should_not_recalculate)
    cached = cache.materialized_discount_history(
        database_path,
        days=31,
        max_points=72,
        year_to_date=False,
    )
    assert cached["estimated"]["change"]["drivers"][0]["key"] == "bemobi_price"

    bundle = cache.materialized_nav_period_bundle(database_path)
    assert bundle["ready"] is True
    assert bundle["source_date"] == "2026-09-03"
    assert list(bundle["periods"]) == list(cache.PERIOD_KEYS)
    assert bundle["missing_periods"] == []


def test_stale_period_cache_falls_back_to_live_calculation(tmp_path, monkeypatch) -> None:
    database_path = str(tmp_path / "stale-period-cache.db")
    _seed_history(database_path, "2026-09-03")

    def initial_payload(database_path_arg=None, *, days: int, max_points: int, year_to_date: bool):
        return {
            "ready": True,
            "estimated": {"ready": True, "to": "2026-09-03", "marker": "cached"},
        }

    monkeypatch.setattr(cache, "discount_history", initial_payload)
    assert cache.materialize_discount_periods(database_path)["written"] == 6

    _seed_history(database_path, "2026-09-04")

    def live_payload(database_path_arg=None, *, days: int, max_points: int, year_to_date: bool):
        return {
            "ready": True,
            "estimated": {"ready": True, "to": "2026-09-04", "marker": "live"},
        }

    monkeypatch.setattr(cache, "discount_history", live_payload)
    result = cache.materialized_discount_history(
        database_path,
        days=31,
        max_points=72,
        year_to_date=False,
    )
    assert result["estimated"]["marker"] == "live"

    bundle = cache.materialized_nav_period_bundle(database_path)
    assert bundle["ready"] is False
    assert bundle["missing_periods"] == list(cache.PERIOD_KEYS)

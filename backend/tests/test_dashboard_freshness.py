import json

from app.dashboard_freshness import enrich_dashboard_summary
from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.history import seed_curated_history
from app.nav.daily_nav import CALCULATION_VERSION


def _insert_core_snapshot(database: str, *, bmob3_date: str, fx_date: str, otec_date: str) -> None:
    components = {
        "scope": "CORE",
        "as_of_date": "2026-08-17",
        "bmob3": {
            "price_date": bmob3_date,
            "price_observed_at": f"{bmob3_date}T21:00:00Z",
            "price_type": "CLOSE",
            "brl_nok_date": fx_date,
            "brl_nok_observed_at": f"{fx_date}T14:00:00Z",
            "brl_nok_source": "NORGES_BANK",
        },
        "otec": {
            "price_date": otec_date,
            "price_observed_at": f"{otec_date}T12:00:00Z",
            "price_type": "LAST",
        },
    }
    with get_connection(database) as connection:
        connection.execute(
            """
            INSERT INTO nav_snapshots(
                as_of_at, nav_total_nok, nav_per_share_nok, otec_price_nok,
                discount_pct, bemobi_value_nok, cash_estimate_nok,
                other_net_assets_nok, shares_outstanding, calculation_version,
                inputs_hash, status, nav_scope, components_json, quality_notes
            ) VALUES (
                '2026-08-17T23:59:59Z', '1000', '20', '17.2', '14',
                '800', '200', '0', 50000000, ?, 'hash', 'ESTIMATED',
                'CORE', ?, 'test'
            )
            """,
            (CALCULATION_VERSION, json.dumps(components)),
        )
        connection.commit()


def test_freshness_marks_cross_market_dates_as_mixed_and_hides_stale_ownership(tmp_path) -> None:
    database = str(tmp_path / "freshness.db")
    init_database(database)
    seed_curated_history(database)
    _insert_core_snapshot(
        database,
        otec_date="2026-08-17",
        bmob3_date="2026-08-14",
        fx_date="2026-08-14",
    )

    result = enrich_dashboard_summary(
        {
            "ready": True,
            "as_of_date": "2026-08-17",
            "bemobi_ownership_pct": 35.992,
        },
        database,
    )

    assert result["market_timestamps"]["status"] == "MIXED"
    assert result["market_timestamps"]["indicative"] is True
    assert result["market_timestamps"]["component_skew_days"] == 3
    assert result["market_timestamps"]["otec"]["date"] == "2026-08-17"
    assert result["market_timestamps"]["bmob3"]["date"] == "2026-08-14"
    assert result["market_timestamps"]["brl_nok"] == {
        "date": "2026-08-14",
        "observed_at": "2026-08-14T14:00:00Z",
        "source": "NORGES_BANK",
    }
    assert result["bemobi_ownership_quality"] == "STALE_REPORTED"
    assert result["bemobi_ownership_reported_pct"] is not None
    assert result["bemobi_ownership_pct"] is None


def test_freshness_marks_same_date_inputs_as_aligned(tmp_path) -> None:
    database = str(tmp_path / "aligned.db")
    init_database(database)
    seed_curated_history(database)
    _insert_core_snapshot(
        database,
        otec_date="2026-08-17",
        bmob3_date="2026-08-17",
        fx_date="2026-08-17",
    )

    result = enrich_dashboard_summary(
        {"ready": True, "as_of_date": "2026-08-17"},
        database,
    )

    assert result["market_timestamps"]["status"] == "ALIGNED"
    assert result["market_timestamps"]["indicative"] is False
    assert result["market_timestamps"]["component_skew_days"] == 0

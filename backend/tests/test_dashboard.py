import json

from app.dashboard import dashboard_history, dashboard_summary
from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.history import seed_curated_history
from app.nav.daily_nav import CALCULATION_VERSION


def _insert_snapshot(connection, *, day: str, nav: str, otec: str, discount: str, cash: str, bmob3: str, brl: str, status: str):
    components = {
        "bmob3": {
            "price_brl": bmob3,
            "brl_nok": brl,
            "price_source": "B3",
            "price_quality": "DIRECT",
        },
        "otec": {
            "price_nok": otec,
            "price_source": "EURONEXT",
            "price_quality": "DIRECT",
        },
        "cash": {"cash_nok": cash, "quality": "FORECAST_PARTIAL" if status == "DEGRADED" else "ANCHORED_ESTIMATE"},
    }
    connection.execute(
        """
        INSERT INTO nav_snapshots(
            as_of_at, nav_total_nok, nav_per_share_nok, otec_price_nok,
            discount_pct, bemobi_value_nok, cash_estimate_nok,
            other_net_assets_nok, shares_outstanding, calculation_version,
            inputs_hash, status, nav_scope, components_json, quality_notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, '0', ?, ?, ?, ?, 'CORE', ?, ?)
        """,
        (
            f"{day}T23:59:59Z",
            "1500000000",
            nav,
            otec,
            discount,
            "1350000000",
            cash,
            70_000_000,
            CALCULATION_VERSION,
            f"hash-{day}",
            status,
            json.dumps(components),
            "CORE NAV test snapshot",
        ),
    )


def test_dashboard_summary_uses_latest_real_snapshot(tmp_path):
    db = str(tmp_path / "dashboard.db")
    init_database(db)
    seed_curated_history(db)
    with get_connection(db) as connection:
        _insert_snapshot(
            connection,
            day="2026-08-13",
            nav="23.00",
            otec="17.86",
            discount="22.34782608695652",
            cash="160000000",
            bmob3="22.88",
            brl="1.90",
            status="DEGRADED",
        )
        _insert_snapshot(
            connection,
            day="2026-08-14",
            nav="23.50",
            otec="17.20",
            discount="26.80851063829787",
            cash="158000000",
            bmob3="22.81",
            brl="1.91",
            status="DEGRADED",
        )
        connection.commit()

    result = dashboard_summary(db)
    assert result["ready"] is True
    assert result["data_status"] == "DEGRADED"
    assert result["as_of_date"] == "2026-08-14"
    assert result["nav_per_share"] == 23.5
    assert result["otec_price"] == 17.2
    assert result["bmob3_price"] == 22.81
    assert result["brl_nok"] == 1.91
    assert result["estimated_cash_mnok"] == 158.0
    assert result["bemobi_shares"] == 32719588
    assert result["changes"]["nav_pct"] > 2.17
    assert result["changes"]["otec_pct"] < -3.69
    assert result["cash_quality"] == "FORECAST_PARTIAL"
    assert result["otec_price_source"] == "EURONEXT"


def test_dashboard_summary_returns_not_ready_without_nav(tmp_path):
    db = str(tmp_path / "empty.db")
    init_database(db)
    result = dashboard_summary(db)
    assert result["ready"] is False
    assert result["data_status"] == "not_ready"
    assert "nav_per_share" not in result


def test_dashboard_history_is_bounded_and_keeps_latest_point(tmp_path):
    db = str(tmp_path / "history.db")
    init_database(db)
    seed_curated_history(db)
    with get_connection(db) as connection:
        for day, nav, price, discount in (
            ("2026-08-10", "22", "17", "22.7273"),
            ("2026-08-11", "23", "17.2", "25.2174"),
            ("2026-08-12", "24", "17.9", "25.4167"),
            ("2026-08-13", "23.8", "17.86", "24.9580"),
            ("2026-08-14", "23.5", "17.2", "26.8085"),
        ):
            _insert_snapshot(
                connection,
                day=day,
                nav=nav,
                otec=price,
                discount=discount,
                cash="158000000",
                bmob3="22.81",
                brl="1.91",
                status="BACKFILLED",
            )
        connection.commit()

    result = dashboard_history(db, days=7, max_points=50)
    assert result["ready"] is True
    assert result["raw_count"] == 5
    assert result["point_count"] == 5
    assert result["points"][0]["date"] == "2026-08-10"
    assert result["points"][-1]["date"] == "2026-08-14"
    assert result["points"][-1]["nav_per_share"] == 23.5
    assert result["average_discount_pct"] is not None

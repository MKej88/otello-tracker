from decimal import Decimal

import pytest

from app.dashboard import brl_nok_insights
from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.history import seed_curated_history
from app.nav_waterfall_attribution import symmetric_two_factor_attribution


def _source_id(connection, code: str) -> int:
    return int(
        connection.execute("SELECT id FROM sources WHERE code=?", (code,)).fetchone()[
            "id"
        ]
    )


def _fx(connection, day: str, rate: str) -> None:
    connection.execute(
        """
        INSERT INTO fx_rates(base_currency, quote_currency, observed_at, rate, source_id)
        VALUES ('BRL', 'NOK', ?, ?, ?)
        """,
        (f"{day}T16:00:00Z", rate, _source_id(connection, "NORGES_BANK")),
    )


def _price(connection, day: str, price: str) -> None:
    instrument_id = connection.execute(
        "SELECT id FROM instruments WHERE symbol='BMOB3'"
    ).fetchone()["id"]
    connection.execute(
        """
        INSERT INTO market_prices(
            instrument_id, observed_at, trading_date, price_type, price,
            currency, source_id, quality
        ) VALUES (?, ?, ?, 'CLOSE', ?, 'BRL', ?, 'DIRECT')
        """,
        (
            instrument_id,
            f"{day}T16:00:00Z",
            day,
            price,
            _source_id(connection, "B3"),
        ),
    )


def test_brl_insights_changes_range_fallback_and_nav_driver(tmp_path) -> None:
    database = str(tmp_path / "brl.db")
    init_database(database)
    seed_curated_history(database)
    with get_connection(database) as connection:
        for day, rate in (
            ("2025-09-01", "1.50"),
            ("2026-06-30", "1.70"),
            ("2026-07-31", "1.80"),
            ("2026-08-28", "1.90"),
            ("2026-08-31", "2.00"),
        ):
            _fx(connection, day, rate)
        _price(connection, "2026-07-31", "20")
        _price(connection, "2026-08-31", "22")
        document_id = connection.execute(
            "SELECT id FROM source_documents ORDER BY id LIMIT 1"
        ).fetchone()["id"]
        connection.execute(
            """
            INSERT INTO cash_anchors(
                as_of_date, amount_nok, anchor_type, source_document_id
            ) VALUES ('2026-06-30', '1', 'REPORTED', ?)
            """,
            (document_id,),
        )
        connection.execute("""
            INSERT INTO nav_snapshots(
                as_of_at, nav_total_nok, nav_per_share_nok, bemobi_value_nok,
                cash_estimate_nok, other_net_assets_nok, shares_outstanding,
                calculation_version, inputs_hash, status, nav_scope
            ) VALUES (
                '2026-07-31T23:59:59Z', '1', '1', '1', '1', '0', 70000000,
                'test', 'test', 'OK', 'CORE'
            )
            """)
        result = brl_nok_insights(connection, as_of_date="2026-08-31")

    assert result["daily_pct"] == pytest.approx(5.2631579)
    assert result["month_pct"] == pytest.approx(11.1111111)
    assert result["month_reference_date"] == "2026-07-31"
    assert result["quarter_label"] == "Q2 26"
    assert result["quarter_pct"] == pytest.approx(17.6470588)
    assert result["range_1y"] == {
        "low": 1.5,
        "high": 2.0,
        "position_pct": 100.0,
    }

    driver = symmetric_two_factor_attribution(
        shares=32_719_588,
        anchor_price=Decimal("20"),
        current_price=Decimal("22"),
        anchor_fx=Decimal("1.8"),
        current_fx=Decimal("2"),
    )
    expected = float(driver["fx_effect_nok"] / 70_000_000)
    assert result["nav_effect_1m_per_share_nok"] == pytest.approx(expected)


def test_brl_insights_handles_missing_and_flat_history(tmp_path) -> None:
    database = str(tmp_path / "missing.db")
    init_database(database)
    with get_connection(database) as connection:
        missing = brl_nok_insights(connection, as_of_date="2026-08-31")
        _fx(connection, "2026-08-29", "1.80")
        flat = brl_nok_insights(connection, as_of_date="2026-08-31")

    assert missing["daily_pct"] is None
    assert missing["range_1y"] == {
        "low": None,
        "high": None,
        "position_pct": None,
    }
    assert flat["daily_pct"] is None
    assert flat["month_pct"] is None
    assert flat["range_1y"] == {
        "low": 1.8,
        "high": 1.8,
        "position_pct": None,
    }

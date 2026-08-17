from datetime import date, timedelta
from decimal import Decimal
import json

from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.db.repository import upsert_fx_rate, upsert_market_price
from app.history import seed_curated_history
from app.nav.other_net_assets import (
    rebuild_daily_other_net_assets,
    rebuild_other_net_assets_anchors,
)


def _seed_daily_fx(connection, start: str, end: str) -> None:
    current = date.fromisoformat(start)
    stop = date.fromisoformat(end)
    option_grant = date(2025, 9, 15)
    while current <= stop:
        day = current.isoformat()
        upsert_fx_rate(
            connection,
            base_currency="USD",
            quote_currency="NOK",
            observed_at=f"{day}T16:00:00Z",
            rate="10",
            source_code="MANUAL",
        )
        upsert_fx_rate(
            connection,
            base_currency="BRL",
            quote_currency="NOK",
            observed_at=f"{day}T16:00:00Z",
            rate="2",
            source_code="MANUAL",
        )
        if current >= option_grant:
            upsert_market_price(
                connection,
                symbol="OTEC",
                observed_at=f"{day}T15:30:00Z",
                trading_date=day,
                price_type="CLOSE",
                price="18.15",
                currency="NOK",
                source_code="MANUAL",
            )
        current += timedelta(days=1)


def _daily(connection, day: str):
    return connection.execute(
        """
        SELECT amount_nok, base_amount_usd, base_amount_nok,
               associated_receivable_nok, receivable_quality,
               receivable_components_json, option_liability_nok,
               option_liability_usd, option_quality, quality
        FROM other_net_assets_daily_estimates
        WHERE estimate_date = ?
        """,
        (day,),
    ).fetchone()


def test_reported_ona_is_decomposed_into_base_bemobi_receivable_and_option_liability(tmp_path):
    db = str(tmp_path / "decomposition.db")
    init_database(db)
    seed_curated_history(db)

    with get_connection(db) as connection:
        rows = {
            row["as_of_date"]: row
            for row in connection.execute(
                """
                SELECT as_of_date, other_net_assets_reported,
                       associated_receivable_reported,
                       base_other_net_assets_reported,
                       option_liability_reported,
                       base_other_net_assets_ex_option_reported
                FROM other_net_assets_reported_anchors
                WHERE as_of_date IN ('2023-12-31', '2024-12-31', '2025-12-31')
                """
            )
        }

        assert rows["2023-12-31"]["other_net_assets_reported"] == "3261000"
        assert rows["2023-12-31"]["associated_receivable_reported"] == "3237000"
        assert rows["2023-12-31"]["base_other_net_assets_reported"] == "24000"

        assert rows["2024-12-31"]["other_net_assets_reported"] == "2987000"
        assert rows["2024-12-31"]["associated_receivable_reported"] == "3452000"
        assert rows["2024-12-31"]["base_other_net_assets_reported"] == "-465000"

        fy25 = rows["2025-12-31"]
        assert fy25["other_net_assets_reported"] == "2974000"
        assert fy25["option_liability_reported"] == "314000"
        assert fy25["base_other_net_assets_ex_option_reported"] == "3288000"
        assert Decimal(fy25["base_other_net_assets_ex_option_reported"]) - Decimal(
            fy25["option_liability_reported"]
        ) == Decimal(fy25["other_net_assets_reported"])

        for day in ("2023-12-31", "2024-12-31"):
            row = rows[day]
            assert Decimal(row["other_net_assets_reported"]) == (
                Decimal(row["base_other_net_assets_reported"])
                + Decimal(row["associated_receivable_reported"])
            )


def test_bemobi_receivable_lives_from_ex_date_until_day_before_payment(tmp_path):
    db = str(tmp_path / "lifecycle.db")
    init_database(db)
    seed_curated_history(db)

    with get_connection(db) as connection:
        _seed_daily_fx(connection, "2022-06-30", "2025-01-08")
        connection.commit()

    rebuild_other_net_assets_anchors(db)
    result = rebuild_daily_other_net_assets(db, end_date="2025-01-08")
    assert result["written"] > 0
    assert result["skipped_missing_fx"] == 0

    with get_connection(db) as connection:
        before_jcp = _daily(connection, "2023-12-18")
        ex_jcp = _daily(connection, "2023-12-19")
        year_end_2023 = _daily(connection, "2023-12-31")
        before_jcp_payment = _daily(connection, "2024-05-01")
        jcp_payment = _daily(connection, "2024-05-02")

        assert before_jcp is not None
        assert ex_jcp is not None
        assert year_end_2023 is not None
        assert before_jcp_payment is not None
        assert jcp_payment is not None
        assert Decimal(before_jcp["associated_receivable_nok"]) == 0
        assert Decimal(ex_jcp["associated_receivable_nok"]) > 0
        assert ex_jcp["receivable_quality"] == "REPORTED_CALIBRATED"
        assert Decimal(year_end_2023["associated_receivable_nok"]) == Decimal("32370000")
        assert Decimal(year_end_2023["base_amount_nok"]) == Decimal("240000")
        assert Decimal(year_end_2023["amount_nok"]) == Decimal("32610000")
        assert Decimal(before_jcp_payment["associated_receivable_nok"]) > 0
        assert Decimal(jcp_payment["associated_receivable_nok"]) == 0
        assert jcp_payment["receivable_quality"] == "NONE"

        before_dividend = _daily(connection, "2024-12-17")
        ex_dividend = _daily(connection, "2024-12-18")
        year_end_2024 = _daily(connection, "2024-12-31")
        before_dividend_payment = _daily(connection, "2025-01-06")
        dividend_payment = _daily(connection, "2025-01-07")

        assert before_dividend is not None
        assert ex_dividend is not None
        assert year_end_2024 is not None
        assert before_dividend_payment is not None
        assert dividend_payment is not None
        assert Decimal(before_dividend["associated_receivable_nok"]) == 0
        assert Decimal(ex_dividend["associated_receivable_nok"]) > 0
        assert ex_dividend["receivable_quality"] == "REPORTED_CALIBRATED"
        assert Decimal(year_end_2024["associated_receivable_nok"]) == Decimal("34520000")
        assert Decimal(year_end_2024["base_amount_nok"]) == Decimal("-4650000")
        assert Decimal(year_end_2024["amount_nok"]) == Decimal("29870000")
        assert Decimal(before_dividend_payment["associated_receivable_nok"]) > 0
        assert Decimal(dividend_payment["associated_receivable_nok"]) == 0
        assert dividend_payment["receivable_quality"] == "NONE"

        components = json.loads(year_end_2024["receivable_components_json"])
        assert len(components) == 2
        assert {component["action_type"] for component in components} == {"DIVIDEND", "JCP"}
        assert {component["component_group"] for component in components} == {"bemobi-2024-12-11-mixed"}
        assert sum(Decimal(component["amount_nok"]) for component in components) == Decimal("34520000")
        for component in components:
            assert component["ex_date"] == "2024-12-18"
            assert component["payment_date"] == "2025-01-07"
            assert component["quality"] == "REPORTED_CALIBRATED"


def test_august_2026_jcp_receivable_and_option_liability_coexist(tmp_path):
    db = str(tmp_path / "august-2026-jcp-lifecycle.db")
    init_database(db)
    seed_curated_history(db)

    with get_connection(db) as connection:
        _seed_daily_fx(connection, "2022-06-30", "2026-08-28")
        connection.commit()

    rebuild_other_net_assets_anchors(db)
    result = rebuild_daily_other_net_assets(db, end_date="2026-08-28")
    assert result["written"] > 0
    assert result["skipped_missing_fx"] == 0
    assert result["skipped_missing_receivable_fx"] == 0
    assert result["skipped_missing_option_inputs"] == 0
    assert result["option_model_days"] > 0

    with get_connection(db) as connection:
        action = connection.execute(
            "SELECT id FROM corporate_actions WHERE external_action_id = 'bemobi-2026-08-28-jcp-2q26'"
        ).fetchone()
        assert action is not None

        before_ex = _daily(connection, "2026-08-16")
        ex_day = _daily(connection, "2026-08-17")
        day_before_payment = _daily(connection, "2026-08-27")
        payment_day = _daily(connection, "2026-08-28")

        assert before_ex is not None
        assert ex_day is not None
        assert day_before_payment is not None
        assert payment_day is not None
        assert Decimal(before_ex["associated_receivable_nok"]) == 0
        assert before_ex["receivable_quality"] == "NONE"
        assert Decimal(before_ex["option_liability_nok"]) > 0
        assert before_ex["option_quality"] == "FORECAST_MARK_TO_MARKET"

        expected_gross_nok = Decimal("6275058.12783696") * Decimal("2")
        assert Decimal(ex_day["associated_receivable_nok"]) == expected_gross_nok
        assert ex_day["receivable_quality"] == "ESTIMATED_GROSS"
        assert Decimal(day_before_payment["associated_receivable_nok"]) == expected_gross_nok
        assert day_before_payment["receivable_quality"] == "ESTIMATED_GROSS"

        components = json.loads(ex_day["receivable_components_json"])
        assert len(components) == 1
        component = components[0]
        assert component["corporate_action_id"] == action["id"]
        assert component["action_type"] == "JCP"
        assert component["ex_date"] == "2026-08-17"
        assert component["payment_date"] == "2026-08-28"
        assert component["holding_shares"] == 32719588
        assert Decimal(component["gross_brl"]) == Decimal("6275058.12783696")
        assert component["quality"] == "ESTIMATED_GROSS"

        assert Decimal(payment_day["associated_receivable_nok"]) == 0
        assert payment_day["receivable_quality"] == "NONE"

from decimal import Decimal

from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.db.repository import upsert_fx_rate, upsert_market_price
from app.history import seed_curated_history
from app.nav.daily_nav import CALCULATION_VERSION as CORE_VERSION
from app.nav.full_nav import FULL_CALCULATION_VERSION, rebuild_daily_full_nav
from app.nav.other_net_assets import (
    rebuild_daily_other_net_assets,
    rebuild_other_net_assets_anchors,
)


def _seed_usd_nok(connection, dates):
    for day, rate in dates:
        upsert_fx_rate(
            connection,
            base_currency="USD",
            quote_currency="NOK",
            observed_at=f"{day}T16:00:00Z",
            rate=rate,
            source_code="MANUAL",
        )


def test_reported_other_net_assets_reconcile_and_preserve_restatements(tmp_path):
    db = str(tmp_path / "full.db")
    init_database(db)
    seed_curated_history(db)

    with get_connection(db) as connection:
        rows = {
            row["as_of_date"]: row
            for row in connection.execute(
                """
                SELECT as_of_date, other_net_assets_reported,
                       associated_receivable_reported, base_other_net_assets_reported,
                       option_liability_reported, base_other_net_assets_ex_option_reported,
                       precision_status, restated
                FROM other_net_assets_reported_anchors ORDER BY as_of_date
                """
            )
        }
        assert len(rows) == 8
        assert rows["2022-06-30"]["other_net_assets_reported"] == "1400000"
        assert rows["2022-06-30"]["precision_status"] == "ROUNDED_0_1M"

        assert rows["2023-12-31"]["other_net_assets_reported"] == "3261000"
        assert rows["2023-12-31"]["associated_receivable_reported"] == "3237000"
        assert rows["2023-12-31"]["base_other_net_assets_reported"] == "24000"
        assert rows["2023-12-31"]["restated"] == 1

        assert rows["2024-12-31"]["other_net_assets_reported"] == "2987000"
        assert rows["2024-12-31"]["associated_receivable_reported"] == "3452000"
        assert rows["2024-12-31"]["base_other_net_assets_reported"] == "-465000"
        assert rows["2024-12-31"]["restated"] == 1

        assert rows["2025-06-30"]["other_net_assets_reported"] == "-5000"
        assert rows["2025-12-31"]["other_net_assets_reported"] == "2974000"
        assert rows["2025-12-31"]["option_liability_reported"] == "314000"
        assert rows["2025-12-31"]["base_other_net_assets_ex_option_reported"] == "3288000"

        provenance = connection.execute(
            """
            SELECT COUNT(*) n FROM provenance_records
            WHERE entity_table = 'other_net_assets_reported_anchors'
              AND extraction_method = 'MANUAL'
            """
        ).fetchone()["n"]
        assert provenance == 8 * 9


def test_other_net_assets_daily_marks_post_anchor_option_liability_to_market(tmp_path):
    db = str(tmp_path / "ona.db")
    init_database(db)
    seed_curated_history(db)
    with get_connection(db) as connection:
        _seed_usd_nok(
            connection,
            [
                ("2022-06-30", "10"),
                ("2022-07-01", "10"),
                ("2022-12-31", "10"),
                ("2025-12-31", "10"),
                ("2026-01-01", "10"),
            ],
        )
        upsert_market_price(
            connection,
            symbol="OTEC",
            observed_at="2025-12-31T15:30:00Z",
            trading_date="2025-12-31",
            price_type="CLOSE",
            price="18.15",
            currency="NOK",
            source_code="MANUAL",
        )
        connection.commit()

    anchors = rebuild_other_net_assets_anchors(db)
    assert anchors["written"] >= 3
    daily = rebuild_daily_other_net_assets(db, end_date="2026-01-01")
    assert daily["written"] > 0
    assert daily["skipped_missing_option_inputs"] == 0

    with get_connection(db) as connection:
        first = connection.execute(
            "SELECT amount_usd, amount_nok, quality FROM other_net_assets_daily_estimates WHERE estimate_date='2022-06-30'"
        ).fetchone()
        year_end = connection.execute(
            """
            SELECT amount_usd, base_amount_usd, option_liability_usd, option_quality, quality
            FROM other_net_assets_daily_estimates WHERE estimate_date='2025-12-31'
            """
        ).fetchone()
        after = connection.execute(
            """
            SELECT amount_usd, amount_nok, base_amount_usd, option_liability_usd,
                   option_quality, quality
            FROM other_net_assets_daily_estimates WHERE estimate_date='2026-01-01'
            """
        ).fetchone()
        assert first["amount_usd"] == "1400000"
        assert Decimal(first["amount_nok"]) == Decimal("14000000")
        assert first["quality"] == "REPORTED_ANCHOR"

        assert year_end["amount_usd"] == "2974000"
        assert Decimal(year_end["base_amount_usd"]) == Decimal("3288000")
        assert Decimal(year_end["option_liability_usd"]) == Decimal("314000")
        assert year_end["option_quality"] == "REPORTED_CALIBRATED"

        assert after is not None
        assert after["quality"] == "FORECAST_PARTIAL"
        assert after["option_quality"] == "FORECAST_MARK_TO_MARKET"
        assert Decimal(after["option_liability_usd"]) > 0
        assert Decimal(after["amount_usd"]) == (
            Decimal(after["base_amount_usd"]) - Decimal(after["option_liability_usd"])
        )
        assert Decimal(after["amount_nok"]) == Decimal(after["amount_usd"]) * Decimal("10")


def test_full_nav_is_separate_and_exactly_core_plus_other_net_assets(tmp_path):
    db = str(tmp_path / "invariant.db")
    init_database(db)

    with get_connection(db) as connection:
        connection.execute(
            """
            INSERT INTO nav_snapshots(
                as_of_at, nav_total_nok, nav_per_share_nok, otec_price_nok,
                discount_pct, bemobi_value_nok, cash_estimate_nok,
                other_net_assets_nok, shares_outstanding, calculation_version,
                inputs_hash, status, nav_scope, components_json, quality_notes
            ) VALUES (
                '2022-06-29T23:59:59Z', '1000000000', '10', '8', '20',
                '900000000', '100000000', '0', 100000000, ?, 'core-before',
                'BACKFILLED', 'CORE', '{}', 'core before first full anchor'
            )
            """,
            (CORE_VERSION,),
        )
        connection.execute(
            """
            INSERT INTO nav_snapshots(
                as_of_at, nav_total_nok, nav_per_share_nok, otec_price_nok,
                discount_pct, bemobi_value_nok, cash_estimate_nok,
                other_net_assets_nok, shares_outstanding, calculation_version,
                inputs_hash, status, nav_scope, components_json, quality_notes
            ) VALUES (
                '2022-06-30T23:59:59Z', '1000000000', '10', '8', '20',
                '900000000', '100000000', '0', 100000000, ?, 'core-anchor',
                'BACKFILLED', 'CORE', '{}', 'core at full anchor'
            )
            """,
            (CORE_VERSION,),
        )
        source_id = connection.execute("SELECT id FROM sources WHERE code='MANUAL'").fetchone()["id"]
        cursor = connection.execute(
            "INSERT INTO source_documents(source_id, document_type, title, url, metadata_json) VALUES (?, 'TEST', 'ONA test', 'manual://ona', '{}')",
            (source_id,),
        )
        doc_id = cursor.lastrowid
        cursor = connection.execute(
            """
            INSERT INTO other_net_assets_reported_anchors(
                as_of_date, total_assets_reported, cash_reported, bemobi_carrying_reported,
                total_liabilities_reported, reported_currency, other_net_assets_reported,
                associated_receivable_reported, base_other_net_assets_reported,
                precision_status, restated, source_document_id
            ) VALUES ('2022-06-30','0','0','0','0','USD','1400000','0','1400000','EXACT',0,?)
            """,
            (doc_id,),
        )
        anchor_id = cursor.lastrowid
        connection.execute(
            """
            INSERT INTO other_net_assets_daily_estimates(
                estimate_date, amount_usd, usd_nok_rate, amount_nok, quality,
                start_anchor_id, end_anchor_id, inputs_hash, notes,
                base_amount_usd, base_amount_nok, associated_receivable_nok,
                receivable_quality, receivable_components_json
            ) VALUES (
                '2022-06-30','1400000','10','14000000','REPORTED_ANCHOR',?,?,
                'ona-hash','test','1400000','14000000','0','NONE','[]'
            )
            """,
            (anchor_id, anchor_id),
        )
        connection.commit()

    result = rebuild_daily_full_nav(db)
    assert result["written"] == 1

    with get_connection(db) as connection:
        core_count = connection.execute(
            "SELECT COUNT(*) n FROM nav_snapshots WHERE calculation_version=?",
            (CORE_VERSION,),
        ).fetchone()["n"]
        full = connection.execute(
            """
            SELECT nav_total_nok, nav_per_share_nok, other_net_assets_nok,
                   shares_outstanding, nav_scope, components_json
            FROM nav_snapshots WHERE calculation_version=?
            """,
            (FULL_CALCULATION_VERSION,),
        ).fetchone()
        assert core_count == 2
        assert full["nav_scope"] == "FULL"
        assert Decimal(full["nav_total_nok"]) == Decimal("1014000000")
        assert Decimal(full["nav_per_share_nok"]) - Decimal("10") == Decimal("14000000") / Decimal("100000000")
        assert Decimal(full["other_net_assets_nok"]) == Decimal("14000000")
        assert '"associated_receivable_nok": "0"' in full["components_json"]
        assert '"option_liability"' in full["components_json"]
        assert connection.execute(
            "SELECT COUNT(*) n FROM nav_snapshots WHERE calculation_version=? AND substr(as_of_at,1,10)<'2022-06-30'",
            (FULL_CALCULATION_VERSION,),
        ).fetchone()["n"] == 0

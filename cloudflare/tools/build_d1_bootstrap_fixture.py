from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.db.connection import get_connection  # noqa: E402
from app.db.migration_runner import init_database  # noqa: E402
from app.history import seed_curated_history  # noqa: E402

FIXTURE_DATE = "2026-08-14"


def build_fixture(database_path: str) -> dict:
    path = Path(database_path)
    if path.exists():
        path.unlink()
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(path) + suffix)
        if sidecar.exists():
            sidecar.unlink()

    migrations = init_database(database_path)
    history = seed_curated_history(database_path)

    with get_connection(database_path) as connection:
        source_ids = {
            row["code"]: row["id"]
            for row in connection.execute("SELECT id, code FROM sources")
        }
        instrument_ids = {
            row["symbol"]: row["id"]
            for row in connection.execute("SELECT id, symbol FROM instruments")
        }

        cursor = connection.execute(
            """
            INSERT INTO source_documents(
                source_id, external_id, document_type, title, published_at, url,
                content_sha256, metadata_json
            ) VALUES (?, 'd1-ci-fixture', 'TEST_FIXTURE', 'D1 bootstrap CI fixture',
                      ?, 'https://example.test/d1-ci-fixture',
                      'fixture-sha256', '{"fixture":true}')
            """,
            (source_ids["MANUAL"], f"{FIXTURE_DATE}T12:00:00Z"),
        )
        fixture_document_id = int(cursor.lastrowid)

        connection.executemany(
            """
            INSERT INTO market_prices(
                instrument_id, observed_at, trading_date, price_type, price,
                currency, source_id, source_document_id, quality, metadata_json
            ) VALUES (?, ?, ?, 'CLOSE', ?, ?, ?, NULL, 'DIRECT', ?)
            """,
            [
                (
                    instrument_ids["OTEC"],
                    f"{FIXTURE_DATE}T14:30:00Z",
                    FIXTURE_DATE,
                    "17.04",
                    "NOK",
                    source_ids["EURONEXT"],
                    '{"fixture":"otec"}',
                ),
                (
                    instrument_ids["BMOB3"],
                    f"{FIXTURE_DATE}T20:00:00Z",
                    FIXTURE_DATE,
                    "22.80",
                    "BRL",
                    source_ids["B3"],
                    '{"fixture":"bmob3"}',
                ),
            ],
        )
        connection.execute(
            """
            INSERT INTO market_activity(
                instrument_id, trading_date, volume_shares, last_price_nok,
                source_id, quality, metadata_json
            ) VALUES (?, ?, 250000, '17.04', ?, 'HISTORICAL_EXPORT', '{"fixture":true}')
            """,
            (instrument_ids["OTEC"], FIXTURE_DATE, source_ids["EURONEXT"]),
        )
        connection.executemany(
            """
            INSERT INTO fx_rates(base_currency, quote_currency, observed_at, rate, source_id)
            VALUES (?, 'NOK', ?, ?, ?)
            """,
            [
                ("BRL", f"{FIXTURE_DATE}T14:15:00Z", "1.915", source_ids["ECB"]),
                ("USD", f"{FIXTURE_DATE}T14:15:00Z", "10.58", source_ids["ECB"]),
            ],
        )

        program_cursor = connection.execute(
            """
            INSERT INTO buyback_programs(
                external_program_id, announced_at, start_date, end_date,
                max_shares, max_amount_nok, status, source_document_id,
                notes, max_price_nok
            ) VALUES (
                'D1-CI-2026', '2026-08-01T06:00:00Z', '2026-08-01', '2026-09-30',
                1000000, '20000000', 'ACTIVE', ?, 'CI fixture only', '25.00'
            )
            """,
            (fixture_document_id,),
        )
        program_id = int(program_cursor.lastrowid)
        buyback_cursor = connection.execute(
            """
            INSERT INTO buybacks(
                program_id, trade_date, shares, avg_price_nok, amount_nok,
                cumulative_program_shares, treasury_shares_after,
                source_document_id, cumulative_program_avg_price_nok,
                cumulative_program_amount_nok, period_start
            ) VALUES (?, ?, 1000, '17.00', '17000.00', 1000, 1000, ?, '17.00', '17000.00', ?)
            """,
            (program_id, FIXTURE_DATE, fixture_document_id, FIXTURE_DATE),
        )
        buyback_id = int(buyback_cursor.lastrowid)

        connection.execute(
            """
            INSERT INTO cash_movements(
                movement_date, movement_type, amount_nok, currency, description,
                source_document_id, confidence, external_movement_id
            ) VALUES (?, 'OTHER', '1234.50', 'NOK', 'D1 CI fixture movement',
                      ?, 'MANUAL', 'D1-CI-CASH-1')
            """,
            (FIXTURE_DATE, fixture_document_id),
        )
        connection.execute(
            """
            INSERT INTO buyback_daily_transactions(
                weekly_buyback_id, trade_date, shares, avg_price_nok, amount_nok,
                trade_count, source_document_id, quality, metadata_json
            ) VALUES (?, ?, 1000, '17.00', '17000.00', 4, ?, 'RECONCILED', '{"fixture":true}')
            """,
            (buyback_id, FIXTURE_DATE, fixture_document_id),
        )

        connection.execute(
            """
            INSERT INTO cash_period_calibrations(
                start_anchor_date, end_anchor_date, start_cash_nok, end_cash_nok,
                known_movements_nok, residual_nok, residual_per_day_nok,
                calendar_days, inputs_hash, quality, notes
            ) VALUES (
                '2026-06-30', '2026-08-14', '100000000', '99000000',
                '-500000', '-500000', '-11111.1111111111', 45,
                'fixture-cash-period', 'ANCHORED', 'CI fixture only'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO cash_daily_estimates(
                estimate_date, cash_nok, period_start_date, period_end_date,
                cumulative_known_movements_nok, cumulative_residual_nok,
                quality, inputs_hash, notes
            ) VALUES (
                ?, '99000000', '2026-06-30', ?, '-500000', '-500000',
                'ANCHORED_ESTIMATE', 'fixture-cash-daily', 'CI fixture only'
            )
            """,
            (FIXTURE_DATE, FIXTURE_DATE),
        )

        ona_anchor = connection.execute(
            "SELECT id FROM other_net_assets_reported_anchors ORDER BY as_of_date DESC, id DESC LIMIT 1"
        ).fetchone()
        if ona_anchor is None:
            raise RuntimeError("Curated history did not create an ONA reported anchor")
        connection.execute(
            """
            INSERT INTO other_net_assets_daily_estimates(
                estimate_date, amount_usd, usd_nok_rate, amount_nok, quality,
                start_anchor_id, end_anchor_id, inputs_hash, notes,
                base_amount_usd, base_amount_nok, associated_receivable_nok,
                receivable_quality, receivable_components_json
            ) VALUES (
                ?, '1000000', '10.58', '10580000', 'FORECAST_PARTIAL',
                ?, NULL, 'fixture-ona-daily', 'CI fixture only',
                '900000', '9522000', '1058000', 'ESTIMATED', '{"fixture":true}'
            )
            """,
            (FIXTURE_DATE, int(ona_anchor["id"])),
        )

        nav_rows = [
            (
                f"{FIXTURE_DATE}T20:05:00Z",
                "500000000",
                "6.25",
                "17.04",
                "-63.3215962441",
                "401000000",
                "99000000",
                "0",
                80000000,
                "d1-ci-core-v1",
                "fixture-nav-core",
                "OK",
                "CORE",
                '{"fixture":"core"}',
            ),
            (
                f"{FIXTURE_DATE}T20:05:00Z",
                "510580000",
                "6.38225",
                "17.04",
                "-62.5454800469",
                "401000000",
                "99000000",
                "10580000",
                80000000,
                "d1-ci-full-v1",
                "fixture-nav-full",
                "ESTIMATED",
                "FULL",
                '{"fixture":"full"}',
            ),
        ]
        connection.executemany(
            """
            INSERT INTO nav_snapshots(
                as_of_at, nav_total_nok, nav_per_share_nok, otec_price_nok,
                discount_pct, bemobi_value_nok, cash_estimate_nok,
                other_net_assets_nok, shares_outstanding, calculation_version,
                inputs_hash, status, nav_scope, components_json, quality_notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'CI fixture only')
            """,
            nav_rows,
        )
        connection.commit()

    return {
        "database": database_path,
        "fixture_date": FIXTURE_DATE,
        "migrations_applied": migrations,
        "history_manifest": history.get("manifest_version"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build deterministic D1 bootstrap CI reference DB")
    parser.add_argument("--database", required=True)
    args = parser.parse_args()
    result = build_fixture(args.database)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()

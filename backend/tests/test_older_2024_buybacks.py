from decimal import Decimal

from app.buybacks.coverage import buyback_coverage_gaps
from app.buybacks.official_backfill import seed_known_official_buybacks
from app.buybacks.older_2024 import OLDER_2024_OFFICIAL_BUYBACKS
from app.buybacks.older_2024_reconciled import reconciled_older_2024_buybacks
from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.history import seed_curated_history


def _by_suffix(rows: list[dict], suffix: str) -> dict:
    return next(row for row in rows if row["url"].endswith(suffix))


def test_raw_issuer_inconsistencies_are_preserved_and_model_rows_are_reconciled() -> None:
    raw_aug = _by_suffix(
        OLDER_2024_OFFICIAL_BUYBACKS,
        "2024-08-11-otello-corporation-share-buyback-program-status",
    )
    raw_jan = _by_suffix(
        OLDER_2024_OFFICIAL_BUYBACKS,
        "2025-01-03-otello-corporation-share-buyback-program-status",
    )
    model = reconciled_older_2024_buybacks()
    model_aug = _by_suffix(
        model,
        "2024-08-11-otello-corporation-share-buyback-program-status",
    )
    model_jan = _by_suffix(
        model,
        "2025-01-03-otello-corporation-share-buyback-program-status",
    )

    assert raw_aug["status"].treasury_shares_after == 4_074_164
    assert model_aug["status"].treasury_shares_after == 3_942_564
    assert "3,942,564" in model_aug["source_note"]

    assert raw_jan["status"].period_amount_nok == Decimal("1485870")
    assert model_jan["status"].period_amount_nok == Decimal("1485686")
    assert "cumulative-reconciled" in model_jan["source_note"]


def test_2024_program_and_february_continuation_reconcile(tmp_path) -> None:
    database = str(tmp_path / "history.db")
    init_database(database)
    seed_curated_history(database)
    seed_known_official_buybacks(database)

    with get_connection(database) as connection:
        july = connection.execute(
            """
            SELECT COUNT(*) AS n, SUM(b.shares) AS shares, SUM(CAST(b.amount_nok AS REAL)) AS amount,
                   MAX(b.trade_date) AS last_date
            FROM buybacks b
            JOIN buyback_programs p ON p.id = b.program_id
            WHERE p.external_program_id = 'otec-buyback-2024-07-22'
            """
        ).fetchone()
        july_last = connection.execute(
            """
            SELECT b.* FROM buybacks b
            JOIN buyback_programs p ON p.id = b.program_id
            WHERE p.external_program_id = 'otec-buyback-2024-07-22'
            ORDER BY b.trade_date DESC LIMIT 1
            """
        ).fetchone()

        feb = connection.execute(
            """
            SELECT COUNT(*) AS n, SUM(b.shares) AS shares, SUM(CAST(b.amount_nok AS REAL)) AS amount,
                   MAX(b.trade_date) AS last_date
            FROM buybacks b
            JOIN buyback_programs p ON p.id = b.program_id
            WHERE p.external_program_id = 'otec-buyback-2025-02-03'
            """
        ).fetchone()
        feb_last = connection.execute(
            """
            SELECT b.* FROM buybacks b
            JOIN buyback_programs p ON p.id = b.program_id
            WHERE p.external_program_id = 'otec-buyback-2025-02-03'
            ORDER BY b.trade_date DESC LIMIT 1
            """
        ).fetchone()

    assert july["n"] == 26
    assert july["shares"] == 4_554_896
    assert july["last_date"] == "2025-01-17"
    # Published rounded weekly considerations differ by a net NOK 1 from the final
    # cumulative amount after the material 3 Jan discrepancy is reconciled.
    assert abs(Decimal(str(july["amount"])) - Decimal("36256303")) <= Decimal("1")
    assert july_last["cumulative_program_shares"] == 4_554_896
    assert july_last["cumulative_program_amount_nok"] == "36256303"
    assert july_last["treasury_shares_after"] == 8_243_260

    assert feb["n"] == 3
    assert feb["shares"] == 866_690
    assert Decimal(str(feb["amount"])) == Decimal("6576548")
    assert feb["last_date"] == "2025-02-19"
    assert feb_last["cumulative_program_shares"] == 866_690
    assert feb_last["cumulative_program_amount_nok"] == "6576548"
    assert feb_last["treasury_shares_after"] == 9_109_950

    relevant_gaps = [
        gap
        for gap in buyback_coverage_gaps(database)
        if gap["program"] in {"otec-buyback-2024-07-22", "otec-buyback-2025-02-03"}
    ]
    assert relevant_gaps == []


def test_effective_capital_reductions_drive_daily_outstanding_share_counts(tmp_path) -> None:
    database = str(tmp_path / "share-counts.db")
    init_database(database)
    seed_curated_history(database)
    seed_known_official_buybacks(database)

    with get_connection(database) as connection:
        march = connection.execute(
            """
            SELECT total_shares, treasury_shares, outstanding_shares
            FROM otello_share_counts
            WHERE effective_from = '2025-03-05'
            ORDER BY id DESC LIMIT 1
            """
        ).fetchone()
        september = connection.execute(
            """
            SELECT total_shares, treasury_shares, outstanding_shares
            FROM otello_share_counts
            WHERE effective_from = '2025-09-20'
            ORDER BY id DESC LIMIT 1
            """
        ).fetchone()
        aug9 = connection.execute(
            """
            SELECT total_shares, treasury_shares, outstanding_shares
            FROM otello_share_counts
            WHERE effective_from = '2024-08-09'
              AND notes LIKE 'Treasury shares from weekly %'
            ORDER BY id DESC LIMIT 1
            """
        ).fetchone()
        april11 = connection.execute(
            """
            SELECT total_shares, treasury_shares, outstanding_shares
            FROM otello_share_counts
            WHERE effective_from = '2025-04-11'
              AND notes LIKE 'Treasury shares from weekly %'
            ORDER BY id DESC LIMIT 1
            """
        ).fetchone()
        sep26 = connection.execute(
            """
            SELECT total_shares, treasury_shares, outstanding_shares
            FROM otello_share_counts
            WHERE effective_from = '2025-09-26'
              AND notes LIKE 'Treasury shares from weekly %'
            ORDER BY id DESC LIMIT 1
            """
        ).fetchone()

    assert dict(march) == {
        "total_shares": 81_989_779,
        "treasury_shares": 0,
        "outstanding_shares": 81_989_779,
    }
    assert dict(september) == {
        "total_shares": 73_790_829,
        "treasury_shares": 0,
        "outstanding_shares": 73_790_829,
    }

    assert dict(aug9) == {
        "total_shares": 91_099_729,
        "treasury_shares": 3_942_564,
        "outstanding_shares": 87_157_165,
    }
    assert dict(april11) == {
        "total_shares": 81_989_779,
        "treasury_shares": 709_400,
        "outstanding_shares": 81_280_379,
    }
    assert dict(sep26) == {
        "total_shares": 73_790_829,
        "treasury_shares": 159_500,
        "outstanding_shares": 73_631_329,
    }

from decimal import Decimal

from app.buybacks.official_backfill import seed_known_official_buybacks
from app.buybacks.older_2023 import OLDER_2023_OFFICIAL_BUYBACKS
from app.buybacks.older_2023_h1_2024 import H1_2024_CONTINUATION
from app.buybacks.older_2023_reconciled import reconciled_older_2023_buybacks
from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.estimated_nav_history import _cash_breakdown
from app.history import seed_curated_history


def _by_period_end(rows: list[dict], period_end: str) -> dict:
    return next(row for row in rows if row["status"].period_end == period_end)


def test_2023_raw_weekly_amounts_are_preserved_and_model_uses_cumulative_control() -> None:
    raw = OLDER_2023_OFFICIAL_BUYBACKS
    model = reconciled_older_2023_buybacks()[: len(raw)]

    assert len(raw) == 28
    assert len(model) == 28
    assert sum(row["status"].period_shares for row in raw) == 3_180_027
    assert sum(row["status"].period_amount_nok for row in raw) == Decimal("27290901")

    previous_amount = Decimal("0")
    previous_shares = 0
    corrected_periods = 0
    for raw_row, model_row in zip(raw, model, strict=True):
        raw_status = raw_row["status"]
        model_status = model_row["status"]
        implied_amount = raw_status.cumulative_program_amount_nok - previous_amount
        implied_shares = raw_status.cumulative_program_shares - previous_shares

        assert raw_status.period_shares == implied_shares
        assert model_status.period_shares == raw_status.period_shares
        assert model_status.period_amount_nok == implied_amount
        if raw_status.period_amount_nok != implied_amount:
            corrected_periods += 1
            assert model_row["source_note"]
            assert "cumulative-implied amount" in model_row["source_note"]

        previous_amount = raw_status.cumulative_program_amount_nok
        previous_shares = raw_status.cumulative_program_shares

    assert corrected_periods == 11
    assert sum(row["status"].period_amount_nok for row in model) == Decimal("27290898")

    raw_aug11 = _by_period_end(raw, "2023-08-11")
    model_aug11 = _by_period_end(model, "2023-08-11")
    assert raw_aug11["status"].period_amount_nok == Decimal("1237510")
    assert model_aug11["status"].period_amount_nok == Decimal("1237501")


def test_h1_2024_continuation_reconciles_amount_and_stale_treasury_controls() -> None:
    raw = H1_2024_CONTINUATION
    model = reconciled_older_2023_buybacks()[-len(raw) :]

    assert len(raw) == 22
    assert len(model) == 22
    assert sum(row["status"].period_shares for row in raw) == 508_337
    assert sum(row["status"].period_amount_nok for row in raw) == Decimal("4016107")

    previous_amount = Decimal("27290898")
    previous_shares = 3_180_027
    amount_corrections = 0
    treasury_corrections = 0
    for raw_row, model_row in zip(raw, model, strict=True):
        raw_status = raw_row["status"]
        model_status = model_row["status"]
        implied_amount = raw_status.cumulative_program_amount_nok - previous_amount
        implied_shares = raw_status.cumulative_program_shares - previous_shares

        assert raw_status.period_shares == implied_shares
        assert model_status.period_shares == raw_status.period_shares
        assert model_status.period_amount_nok == implied_amount
        assert model_status.treasury_shares_after == raw_status.cumulative_program_shares

        if raw_status.period_amount_nok != implied_amount:
            amount_corrections += 1
            assert "cumulative-implied amount" in model_row["source_note"]
        if raw_status.treasury_shares_after != raw_status.cumulative_program_shares:
            treasury_corrections += 1
            assert "cumulative share control" in model_row["source_note"]

        previous_amount = raw_status.cumulative_program_amount_nok
        previous_shares = raw_status.cumulative_program_shares

    assert amount_corrections == 11
    assert treasury_corrections == 2
    assert sum(row["status"].period_amount_nok for row in model) == Decimal("4016108")

    raw_feb9 = _by_period_end(raw, "2024-02-09")
    model_feb9 = _by_period_end(model, "2024-02-09")
    assert raw_feb9["status"].treasury_shares_after == 3_273_827
    assert model_feb9["status"].treasury_shares_after == 3_278_492

    raw_mar22 = _by_period_end(raw, "2024-03-22")
    model_mar22 = _by_period_end(model, "2024-03-22")
    assert raw_mar22["status"].treasury_shares_after == 3_322_683
    assert model_mar22["status"].treasury_shares_after == 3_332_775

    final = model[-1]["status"]
    assert final.period_end == "2024-05-31"
    assert final.cumulative_program_shares == 3_688_364
    assert final.cumulative_program_amount_nok == Decimal("31307006")


def test_2023_calendar_program_seeds_cash_and_share_counts(tmp_path) -> None:
    database = str(tmp_path / "history.db")
    init_database(database)
    seed_curated_history(database)
    seed_known_official_buybacks(database)

    with get_connection(database) as connection:
        program = connection.execute(
            """
            SELECT COUNT(*) AS n,
                   SUM(b.shares) AS shares,
                   SUM(CAST(b.amount_nok AS REAL)) AS amount,
                   MAX(b.trade_date) AS last_date
            FROM buybacks b
            JOIN buyback_programs p ON p.id = b.program_id
            WHERE p.external_program_id = 'otec-buyback-2023-06-20'
              AND b.trade_date <= '2023-12-31'
            """
        ).fetchone()
        last = connection.execute(
            """
            SELECT b.*
            FROM buybacks b
            JOIN buyback_programs p ON p.id = b.program_id
            WHERE p.external_program_id = 'otec-buyback-2023-06-20'
              AND b.trade_date <= '2023-12-31'
            ORDER BY b.trade_date DESC LIMIT 1
            """
        ).fetchone()
        year_end = connection.execute(
            """
            SELECT total_shares, treasury_shares, outstanding_shares
            FROM otello_share_counts
            WHERE effective_from = '2023-12-31'
            ORDER BY id DESC LIMIT 1
            """
        ).fetchone()

        period = _cash_breakdown(
            connection,
            start_date="2023-08-30",
            current_date="2023-12-31",
        )

    assert program["n"] == 28
    assert program["shares"] == 3_180_027
    assert Decimal(str(program["amount"])) == Decimal("27290898")
    assert program["last_date"] == "2023-12-29"
    assert last["cumulative_program_shares"] == 3_180_027
    assert last["cumulative_program_amount_nok"] == "27290898"
    assert last["treasury_shares_after"] == 3_180_027

    assert dict(year_end) == {
        "total_shares": 91_099_729,
        "treasury_shares": 3_180_027,
        "outstanding_shares": 87_919_702,
    }

    # A 3Y-style period beginning inside the 28 Aug-1 Sep weekly status must not
    # attribute the whole crossing week. The remaining complete 2023 weeks are exact.
    assert period["buyback_cash_nok"] == Decimal("-5680128")
    assert period["weekly_buyback_rows"] == 17
    assert period["cross_start_weekly_excluded"] == 1


def test_h1_2024_continuation_seeds_cash_share_counts_and_3y_attribution(tmp_path) -> None:
    database = str(tmp_path / "history-h1-2024.db")
    init_database(database)
    seed_curated_history(database)
    seed_known_official_buybacks(database)

    with get_connection(database) as connection:
        h1 = connection.execute(
            """
            SELECT COUNT(*) AS n,
                   SUM(b.shares) AS shares,
                   SUM(CAST(b.amount_nok AS REAL)) AS amount,
                   MAX(b.trade_date) AS last_date
            FROM buybacks b
            JOIN buyback_programs p ON p.id = b.program_id
            WHERE p.external_program_id = 'otec-buyback-2023-06-20'
              AND b.trade_date >= '2024-01-01'
              AND b.trade_date <= '2024-06-30'
            """
        ).fetchone()
        last = connection.execute(
            """
            SELECT b.*
            FROM buybacks b
            JOIN buyback_programs p ON p.id = b.program_id
            WHERE p.external_program_id = 'otec-buyback-2023-06-20'
              AND b.trade_date <= '2024-06-30'
            ORDER BY b.trade_date DESC LIMIT 1
            """
        ).fetchone()
        may31 = connection.execute(
            """
            SELECT total_shares, treasury_shares, outstanding_shares
            FROM otello_share_counts
            WHERE effective_from = '2024-05-31'
              AND notes LIKE 'Treasury shares from weekly %'
            ORDER BY id DESC LIMIT 1
            """
        ).fetchone()
        june30 = connection.execute(
            """
            SELECT total_shares, treasury_shares, outstanding_shares
            FROM otello_share_counts
            WHERE effective_from = '2024-06-30'
            ORDER BY id DESC LIMIT 1
            """
        ).fetchone()
        period = _cash_breakdown(
            connection,
            start_date="2023-08-30",
            current_date="2024-06-30",
        )

    assert h1["n"] == 22
    assert h1["shares"] == 508_337
    assert Decimal(str(h1["amount"])) == Decimal("4016108")
    assert h1["last_date"] == "2024-05-31"
    assert last["cumulative_program_shares"] == 3_688_364
    assert last["cumulative_program_amount_nok"] == "31307006"
    assert last["treasury_shares_after"] == 3_688_364

    expected_share_count = {
        "total_shares": 91_099_729,
        "treasury_shares": 3_688_364,
        "outstanding_shares": 87_411_365,
    }
    assert dict(may31) == expected_share_count
    assert dict(june30) == expected_share_count

    assert period["buyback_cash_nok"] == Decimal("-9696236")
    assert period["weekly_buyback_rows"] == 39
    assert period["cross_start_weekly_excluded"] == 1

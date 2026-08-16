from fastapi.testclient import TestClient

from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.history import history_status, seed_curated_history
from app.main import app
from app.settings import settings


def test_curated_history_is_idempotent(tmp_path) -> None:
    database_path = str(tmp_path / "history.db")
    init_database(database_path)

    first = seed_curated_history(database_path)
    second = seed_curated_history(database_path)

    assert first["cash_anchors_written"] == 10
    assert first["share_counts_written"] == 10
    assert first["share_capital_corrections"]["2022"]["share_counts_written"] == 2
    assert first["share_capital_corrections"]["2025"]["share_counts_written"] == 2
    assert first["bemobi_holdings_written"] == 2
    assert first["corporate_actions_written"] == 7

    assert second["cash_anchors_written"] == 0
    assert second["share_counts_written"] == 0
    assert second["share_capital_corrections"]["2022"]["share_counts_written"] == 0
    assert second["share_capital_corrections"]["2025"]["share_counts_written"] == 0
    assert second["bemobi_holdings_written"] == 0
    assert second["corporate_actions_written"] == 0

    with get_connection(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM cash_anchors").fetchone()[0] == 10
        assert connection.execute("SELECT COUNT(*) FROM otello_share_counts").fetchone()[0] == 14
        assert connection.execute("SELECT COUNT(*) FROM bemobi_holdings").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM corporate_actions").fetchone()[0] == 7
        assert connection.execute("SELECT COUNT(*) FROM provenance_records").fetchone()[0] > 40


def test_key_report_anchors_are_exact_and_reconcilable(tmp_path) -> None:
    database_path = str(tmp_path / "anchors.db")
    init_database(database_path)
    seed_curated_history(database_path)

    with get_connection(database_path) as connection:
        cash_2025 = connection.execute(
            """
            SELECT reported_amount, reported_currency, amount_nok
            FROM cash_anchors WHERE as_of_date = '2025-12-31'
            """
        ).fetchone()
        assert cash_2025["reported_amount"] == "15881000"
        assert cash_2025["reported_currency"] == "USD"
        assert cash_2025["amount_nok"] is None

        shares_1h21 = connection.execute(
            """
            SELECT total_shares, treasury_shares, outstanding_shares
            FROM otello_share_counts WHERE effective_from = '2021-06-30'
            """
        ).fetchone()
        assert shares_1h21["total_shares"] == 124_749_727
        assert shares_1h21["treasury_shares"] == 15_904
        assert shares_1h21["outstanding_shares"] == 124_733_823

        shares_fy21 = connection.execute(
            """
            SELECT total_shares, treasury_shares, outstanding_shares
            FROM otello_share_counts WHERE effective_from = '2021-12-31'
            """
        ).fetchone()
        assert shares_fy21["total_shares"] == 112_299_727
        assert shares_fy21["treasury_shares"] == 11_199_998
        assert shares_fy21["outstanding_shares"] == 101_099_729
        assert shares_fy21["total_shares"] - shares_fy21["treasury_shares"] == shares_fy21["outstanding_shares"]

        shares_2024 = connection.execute(
            """
            SELECT total_shares, treasury_shares, outstanding_shares
            FROM otello_share_counts WHERE effective_from = '2024-12-31'
            """
        ).fetchone()
        assert shares_2024["total_shares"] == 91_099_729
        assert shares_2024["treasury_shares"] == 7_493_227
        assert shares_2024["outstanding_shares"] == 83_606_502
        assert shares_2024["total_shares"] - shares_2024["treasury_shares"] == shares_2024["outstanding_shares"]

        shares_2025 = connection.execute(
            """
            SELECT total_shares, treasury_shares, outstanding_shares
            FROM otello_share_counts WHERE effective_from = '2025-12-31'
            """
        ).fetchone()
        assert shares_2025["total_shares"] == 73_790_829
        assert shares_2025["treasury_shares"] == 2_393_742
        assert shares_2025["outstanding_shares"] == 71_397_087

        holdings = connection.execute(
            """
            SELECT effective_from, effective_to, shares, ownership_pct
            FROM bemobi_holdings ORDER BY effective_from
            """
        ).fetchall()
        assert [dict(row) for row in holdings] == [
            {
                "effective_from": "2021-02-10",
                "effective_to": "2021-03-14",
                "shares": 34_553_860,
                "ownership_pct": "38.01",
            },
            {
                "effective_from": "2021-03-15",
                "effective_to": None,
                "shares": 32_719_588,
                "ownership_pct": "36.0",
            },
        ]

        cancellations = connection.execute(
            """
            SELECT announcement_date, quantity
            FROM corporate_actions
            WHERE action_type = 'SHARE_CANCELLATION'
              AND announcement_date <= '2022-06-14'
            ORDER BY announcement_date
            """
        ).fetchall()
        assert [tuple(row) for row in cancellations] == [
            ("2021-06-30", 13_727_702),
            ("2021-11-24", 12_450_000),
            ("2022-03-07", 11_200_000),
            ("2022-06-14", 9_999_998),
        ]

        dividend = connection.execute(
            """
            SELECT amount_per_share, total_amount, currency, ex_date, payment_date
            FROM corporate_actions WHERE action_type = 'DISTRIBUTION'
            """
        ).fetchone()
        assert dividend["amount_per_share"] == "21"
        assert dividend["total_amount"] == "1913094309"
        assert dividend["currency"] == "NOK"
        assert dividend["ex_date"] == "2022-08-09"
        assert dividend["payment_date"] == "2022-08-18"


def test_history_status_exposes_full_report_anchor_coverage(tmp_path) -> None:
    database_path = str(tmp_path / "status.db")
    init_database(database_path)
    seed_curated_history(database_path)

    status = history_status(database_path)
    assert status["manifest_version"] == "2026-08-17.2"
    assert status["cash_anchors"] == {
        "count": 10,
        "from": "2021-06-30",
        "to": "2025-12-31",
    }
    # Ten report-date anchors plus four effective registration anchors needed for
    # daily NAV/share between reports.
    assert status["share_count_anchors"] == {
        "count": 14,
        "from": "2021-06-30",
        "to": "2025-12-31",
    }
    assert status["effective_share_capital_corrections"] == {
        "count": 4,
        "from": "2022-03-07",
        "to": "2025-09-20",
    }
    assert status["known_gaps"] == []


def test_history_status_api_seeds_fresh_database(tmp_path) -> None:
    previous_path = settings.database_path
    settings.database_path = str(tmp_path / "api-history.db")
    try:
        with TestClient(app) as client:
            response = client.get("/api/system/history")
            assert response.status_code == 200
            payload = response.json()
            assert payload["status"] == "ok"
            assert payload["cash_anchors"]["count"] == 10
            assert payload["share_count_anchors"]["count"] == 14
            assert payload["effective_share_capital_corrections"]["count"] == 4
            assert payload["bemobi_holding"]["shares"] == 32_719_588
            assert payload["bemobi_holding"]["effective_from"] == "2021-03-15"
            assert payload["known_gaps"] == []
    finally:
        settings.database_path = previous_path

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
    assert first["share_counts_written"] == 8
    assert first["bemobi_holdings_written"] == 1
    assert first["corporate_actions_written"] == 5

    assert second["cash_anchors_written"] == 0
    assert second["share_counts_written"] == 0
    assert second["bemobi_holdings_written"] == 0
    assert second["corporate_actions_written"] == 0

    with get_connection(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM cash_anchors").fetchone()[0] == 10
        assert connection.execute("SELECT COUNT(*) FROM otello_share_counts").fetchone()[0] == 8
        assert connection.execute("SELECT COUNT(*) FROM bemobi_holdings").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM corporate_actions").fetchone()[0] == 5
        assert connection.execute("SELECT COUNT(*) FROM provenance_records").fetchone()[0] > 30


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

        holding = connection.execute(
            "SELECT shares, ownership_pct FROM bemobi_holdings"
        ).fetchone()
        assert holding["shares"] == 32_719_588
        assert holding["ownership_pct"] == "35.992"

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


def test_history_status_exposes_coverage_and_known_gaps(tmp_path) -> None:
    database_path = str(tmp_path / "status.db")
    init_database(database_path)
    seed_curated_history(database_path)

    status = history_status(database_path)
    assert status["manifest_version"] == "2026-08-16.1"
    assert status["cash_anchors"] == {
        "count": 10,
        "from": "2021-06-30",
        "to": "2025-12-31",
    }
    assert status["share_count_anchors"]["count"] == 8
    gap_codes = {gap["code"] for gap in status["known_gaps"]}
    assert gap_codes == {"OTEC_SHARE_COUNT_2021_EXACT", "BEMOBI_GREENSHOE_EFFECTIVE_DATE"}


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
            assert payload["share_count_anchors"]["count"] == 8
            assert payload["bemobi_holding"]["shares"] == 32_719_588
    finally:
        settings.database_path = previous_path

from app.buybacks.official_backfill import seed_known_official_buybacks
from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.history import seed_curated_history


def test_weekly_buybacks_use_latest_registered_total_share_count(tmp_path) -> None:
    database = str(tmp_path / "ordering.db")
    init_database(database)
    seed_curated_history(database)
    seed_known_official_buybacks(database)

    with get_connection(database) as connection:
        rows = connection.execute(
            """
            SELECT effective_from, total_shares, treasury_shares, outstanding_shares
            FROM otello_share_counts
            WHERE effective_from IN ('2025-02-19', '2025-03-05', '2025-04-11',
                                     '2025-09-20', '2025-09-26')
            ORDER BY effective_from, id
            """
        ).fetchall()

    by_date = {row["effective_from"]: dict(row) for row in rows}
    assert by_date["2025-02-19"]["total_shares"] == 91_099_729
    assert by_date["2025-02-19"]["treasury_shares"] == 9_109_950

    assert by_date["2025-03-05"] == {
        "effective_from": "2025-03-05",
        "total_shares": 81_989_779,
        "treasury_shares": 0,
        "outstanding_shares": 81_989_779,
    }
    assert by_date["2025-04-11"]["total_shares"] == 81_989_779

    assert by_date["2025-09-20"] == {
        "effective_from": "2025-09-20",
        "total_shares": 73_790_829,
        "treasury_shares": 0,
        "outstanding_shares": 73_790_829,
    }
    assert by_date["2025-09-26"]["total_shares"] == 73_790_829

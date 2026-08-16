from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.history import history_status, seed_curated_history


def test_history_wrapper_seeds_effective_2025_capital_anchors(tmp_path) -> None:
    database = str(tmp_path / "history-wrapper.db")
    init_database(database)

    seeded = seed_curated_history(database)
    status = history_status(database)

    assert seeded["manifest_version"] == "2026-08-17.1"
    assert seeded["share_capital_corrections"]["share_counts_written"] == 2
    assert status["manifest_version"] == "2026-08-17.1"
    assert status["effective_share_capital_corrections"] == {
        "count": 2,
        "from": "2025-03-05",
        "to": "2025-09-20",
    }

    with get_connection(database) as connection:
        rows = connection.execute(
            """
            SELECT effective_from, total_shares, treasury_shares, outstanding_shares
            FROM otello_share_counts
            WHERE effective_from IN ('2025-03-05', '2025-09-20')
            ORDER BY effective_from
            """
        ).fetchall()

    assert [dict(row) for row in rows] == [
        {
            "effective_from": "2025-03-05",
            "total_shares": 81_989_779,
            "treasury_shares": 0,
            "outstanding_shares": 81_989_779,
        },
        {
            "effective_from": "2025-09-20",
            "total_shares": 73_790_829,
            "treasury_shares": 0,
            "outstanding_shares": 73_790_829,
        },
    ]

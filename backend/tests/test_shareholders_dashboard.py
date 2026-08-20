from __future__ import annotations

from pathlib import Path

from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.history import seed_curated_history
from app.shareholders import EURONEXT_TOP20_URL, shareholders_dashboard


ROOT = Path(__file__).resolve().parents[2]


def _insert_snapshot(connection, snapshot_date: str, rows: list[tuple[int, str, int, str]]) -> int:
    connection.execute(
        """
        INSERT INTO shareholder_snapshots(
            snapshot_date, source_url, source_kind, total_issued_shares,
            treasury_shares, outstanding_shares
        ) VALUES (?, ?, 'EURONEXT_OMS', 73790829, 3000000, 70790829)
        """,
        (snapshot_date, EURONEXT_TOP20_URL),
    )
    snapshot_id = int(connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])
    connection.executemany(
        """
        INSERT INTO shareholder_snapshot_rows(snapshot_id, rank, shareholder_name, country, shares, ownership_pct)
        VALUES (?, ?, ?, 'NO', ?, ?)
        """,
        [(snapshot_id, rank, name, shares, ownership) for rank, name, shares, ownership in rows],
    )
    return snapshot_id


def test_shareholders_dashboard_tracks_daily_top20_changes(tmp_path) -> None:
    database = str(tmp_path / "shareholders.db")
    init_database(database)
    seed_curated_history(database)

    with get_connection(database) as connection:
        _insert_snapshot(
            connection,
            "2026-08-13",
            [
                (1, "Investor A", 10_000_000, "13.55"),
                (2, "Investor B", 5_000_000, "6.78"),
                (3, "Investor C", 2_000_000, "2.71"),
            ],
        )
        _insert_snapshot(
            connection,
            "2026-08-14",
            [
                (1, "Investor A", 10_500_000, "14.23"),
                (2, "Investor D", 4_500_000, "6.10"),
                (3, "Investor B", 4_000_000, "5.42"),
            ],
        )
        connection.commit()

    result = shareholders_dashboard(database)
    assert result["ready"] is True
    assert result["official_live"]["updated_frequency"] == "DAILY"
    assert result["official_live"]["embed_url"] == EURONEXT_TOP20_URL
    assert result["history"]["snapshot_count"] == 2
    assert result["history"]["comparison_ready"] is True
    assert result["history"]["latest_rows"][0]["shareholder_name"] == "Investor A"

    daily = result["history"]["daily_summary"]
    assert daily["status"] == "CHANGES"
    assert daily["is_previous_day"] is True
    assert daily["change_count"] == 4
    assert daily["message"] == "4 endringer siden i går."

    movement = result["history"]["movement"]
    assert movement is not None
    assert movement["biggest_buyers"][0]["shareholder_name"] == "Investor D"
    assert movement["biggest_buyers"][0]["change_shares"] == 4_500_000
    assert movement["biggest_sellers"][0]["shareholder_name"] == "Investor C"
    assert movement["biggest_sellers"][0]["change_shares"] == -2_000_000
    assert [item["shareholder_name"] for item in movement["new_entries"]] == ["Investor D"]
    assert [item["shareholder_name"] for item in movement["exits"]] == ["Investor C"]


def test_shareholders_dashboard_says_no_changes_since_yesterday(tmp_path) -> None:
    database = str(tmp_path / "shareholders-unchanged.db")
    init_database(database)
    rows = [
        (1, "Investor A", 10_000_000, "13.55"),
        (2, "Investor B", 5_000_000, "6.78"),
        (3, "Investor C", 2_000_000, "2.71"),
    ]
    with get_connection(database) as connection:
        _insert_snapshot(connection, "2026-08-18", rows)
        _insert_snapshot(connection, "2026-08-19", rows)
        connection.commit()

    result = shareholders_dashboard(database)
    daily = result["history"]["daily_summary"]
    assert daily == {
        "status": "NO_CHANGES",
        "message": "Ingen endringer siden i går.",
        "latest_date": "2026-08-19",
        "previous_date": "2026-08-18",
        "is_previous_day": True,
        "change_count": 0,
    }
    assert result["history"]["movement"]["changes"] == []


def test_shareholders_dashboard_does_not_call_a_gap_yesterday(tmp_path) -> None:
    database = str(tmp_path / "shareholders-gap.db")
    init_database(database)
    rows = [(1, "Investor A", 10_000_000, "13.55")]
    with get_connection(database) as connection:
        _insert_snapshot(connection, "2026-08-17", rows)
        _insert_snapshot(connection, "2026-08-19", rows)
        connection.commit()

    result = shareholders_dashboard(database)
    daily = result["history"]["daily_summary"]
    assert daily["is_previous_day"] is False
    assert daily["message"] == "Ingen endringer siden forrige måling (2026-08-17)."


def test_shareholders_is_exposed_in_backend_worker_frontend_and_csp() -> None:
    backend_app = (ROOT / "backend/app/main.py").read_text(encoding="utf-8")
    worker_app = (ROOT / "cloudflare/src/app.py").read_text(encoding="utf-8")
    frontend = (ROOT / "frontend/src/App.tsx").read_text(encoding="utf-8")
    page = (ROOT / "frontend/src/ShareholdersPage.tsx").read_text(encoding="utf-8")
    migration = (ROOT / "backend/app/db/migrations/0018_shareholder_snapshots.sql").read_text(encoding="utf-8")

    assert '@app.get("/api/shareholders/dashboard")' in backend_app
    assert '@app.get("/api/shareholders/dashboard")' in worker_app
    assert 'type View = "Oversikt" | "NAV" | "Tilbakekjøp" | "Bemobi" | "Konsensus" | "Aksjonærer";' in frontend
    assert '{ label: "Aksjonærer", enabled: true }' in frontend
    assert '<ShareholdersPage />' in frontend
    assert 'fetch("/api/shareholders/dashboard")' in page
    assert 'Top 20 største aksjonærer' in page
    assert '<iframe' not in page
    assert 'HENTES DAGLIG' in page
    assert 'daily_summary' in page
    assert 'CREATE TABLE shareholder_snapshots' in migration
    assert 'CREATE TABLE shareholder_snapshot_rows' in migration

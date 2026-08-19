from __future__ import annotations

from pathlib import Path

from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.history import seed_curated_history
from app.shareholders import EURONEXT_TOP20_URL, shareholders_dashboard


ROOT = Path(__file__).resolve().parents[2]


def test_shareholders_dashboard_tracks_weekly_top20_changes(tmp_path) -> None:
    database = str(tmp_path / "shareholders.db")
    init_database(database)
    seed_curated_history(database)

    with get_connection(database) as connection:
        connection.execute(
            """
            INSERT INTO shareholder_snapshots(
                snapshot_date, source_url, source_kind, total_issued_shares,
                treasury_shares, outstanding_shares
            ) VALUES ('2026-08-07', ?, 'MANUAL_VERIFIED', 73790829, 3000000, 70790829)
            """,
            (EURONEXT_TOP20_URL,),
        )
        previous_id = int(connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])
        connection.executemany(
            """
            INSERT INTO shareholder_snapshot_rows(snapshot_id, rank, shareholder_name, country, shares, ownership_pct)
            VALUES (?, ?, ?, 'NO', ?, ?)
            """,
            [
                (previous_id, 1, "Investor A", 10_000_000, "13.55"),
                (previous_id, 2, "Investor B", 5_000_000, "6.78"),
                (previous_id, 3, "Investor C", 2_000_000, "2.71"),
            ],
        )
        connection.execute(
            """
            INSERT INTO shareholder_snapshots(
                snapshot_date, source_url, source_kind, total_issued_shares,
                treasury_shares, outstanding_shares
            ) VALUES ('2026-08-14', ?, 'MANUAL_VERIFIED', 73790829, 3200000, 70590829)
            """,
            (EURONEXT_TOP20_URL,),
        )
        current_id = int(connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])
        connection.executemany(
            """
            INSERT INTO shareholder_snapshot_rows(snapshot_id, rank, shareholder_name, country, shares, ownership_pct)
            VALUES (?, ?, ?, 'NO', ?, ?)
            """,
            [
                (current_id, 1, "Investor A", 10_500_000, "14.23"),
                (current_id, 2, "Investor D", 4_500_000, "6.10"),
                (current_id, 3, "Investor B", 4_000_000, "5.42"),
            ],
        )
        connection.commit()

    result = shareholders_dashboard(database)
    assert result["ready"] is True
    assert result["official_live"]["updated_frequency"] == "WEEKLY"
    assert result["official_live"]["embed_url"] == EURONEXT_TOP20_URL
    assert result["history"]["snapshot_count"] == 2
    assert result["history"]["comparison_ready"] is True
    assert result["history"]["latest_rows"][0]["shareholder_name"] == "Investor A"

    movement = result["history"]["movement"]
    assert movement is not None
    assert movement["biggest_buyers"][0]["shareholder_name"] == "Investor D"
    assert movement["biggest_buyers"][0]["change_shares"] == 4_500_000
    assert movement["biggest_sellers"][0]["shareholder_name"] == "Investor C"
    assert movement["biggest_sellers"][0]["change_shares"] == -2_000_000
    assert [item["shareholder_name"] for item in movement["new_entries"]] == ["Investor D"]
    assert [item["shareholder_name"] for item in movement["exits"]] == ["Investor C"]


def test_shareholders_is_exposed_in_backend_worker_frontend_and_csp() -> None:
    backend_app = (ROOT / "backend/app/main.py").read_text(encoding="utf-8")
    worker_app = (ROOT / "cloudflare/src/app.py").read_text(encoding="utf-8")
    frontend = (ROOT / "frontend/src/App.tsx").read_text(encoding="utf-8")
    page = (ROOT / "frontend/src/ShareholdersPage.tsx").read_text(encoding="utf-8")
    headers = (ROOT / "frontend/public/_headers").read_text(encoding="utf-8")
    migration = (ROOT / "backend/app/db/migrations/0018_shareholder_snapshots.sql").read_text(encoding="utf-8")

    assert '@app.get("/api/shareholders/dashboard")' in backend_app
    assert '@app.get("/api/shareholders/dashboard")' in worker_app
    assert 'type View = "Oversikt" | "NAV" | "Tilbakekjøp" | "Bemobi" | "Konsensus" | "Aksjonærer";' in frontend
    assert '{ label: "Aksjonærer", enabled: true }' in frontend
    assert '<ShareholdersPage />' in frontend
    assert 'fetch("/api/shareholders/dashboard")' in page
    assert 'Top 20 største aksjonærer' in page
    assert 'https://ir.oms.no' in headers
    assert 'CREATE TABLE shareholder_snapshots' in migration
    assert 'CREATE TABLE shareholder_snapshot_rows' in migration

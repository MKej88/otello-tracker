from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.history import seed_curated_history
from app.jobs.preflight import run_preflight

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_BUILDER = ROOT / "cloudflare" / "tools" / "build_d1_bootstrap_fixture.py"
BOOTSTRAP_TOOL = ROOT / "cloudflare" / "tools" / "d1_bootstrap.py"


def test_preflight_rejects_test_fixture_source_documents(tmp_path: Path) -> None:
    database = str(tmp_path / "fixture-sentinel.db")
    init_database(database)
    seed_curated_history(database)

    with get_connection(database) as connection:
        manual_id = int(
            connection.execute("SELECT id FROM sources WHERE code='MANUAL'").fetchone()["id"]
        )
        connection.execute(
            """
            INSERT INTO source_documents(
                source_id, external_id, document_type, title, url
            ) VALUES (?, 'd1-ci-sentinel', 'TEST_FIXTURE', 'CI fixture',
                      'https://example.test/d1-ci-sentinel')
            """,
            (manual_id,),
        )
        connection.commit()

    result = run_preflight(database, target_date="2026-08-17", check_derived=False)
    blockers = {item["name"]: item for item in result["blockers"]}

    assert "production_fixture_sentinel" in blockers
    assert blockers["production_fixture_sentinel"]["details"]["fixture_markers"] == 1


def test_production_bootstrap_mode_refuses_ci_fixture(tmp_path: Path) -> None:
    source = tmp_path / "ci-fixture.db"
    subprocess.run(
        [sys.executable, str(FIXTURE_BUILDER), "--database", str(source)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    sql_path = tmp_path / "production.sql"
    manifest_path = tmp_path / "production.json"
    result = subprocess.run(
        [
            sys.executable,
            str(BOOTSTRAP_TOOL),
            "export",
            "--database",
            str(source),
            "--sql",
            str(sql_path),
            "--manifest",
            str(manifest_path),
            "--production",
            "--date",
            "2026-08-14",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    payload = json.loads(result.stdout)
    blocker_names = {item["name"] for item in payload["blockers"]}

    assert result.returncode == 2
    assert payload["status"] == "blocked"
    assert payload["reason"] == "production_preflight_failed"
    assert "production_fixture_sentinel" in blocker_names
    assert not sql_path.exists()
    assert not manifest_path.exists()

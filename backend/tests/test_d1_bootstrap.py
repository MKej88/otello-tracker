from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from app.db.d1_bootstrap import (
    DATA_TABLES,
    OPERATIONAL_TABLES,
    build_manifest,
    compare_manifest,
    load_manifest_file,
    verify_database,
    write_bootstrap_package,
)

ROOT = Path(__file__).resolve().parents[2]
D1_SCHEMA = ROOT / "cloudflare" / "migrations" / "0001_initial_schema.sql"
D1_REFERENCE_DATA = ROOT / "cloudflare" / "migrations" / "0002_reference_data.sql"
FIXTURE_BUILDER = ROOT / "cloudflare" / "tools" / "build_d1_bootstrap_fixture.py"


def _build_fixture(tmp_path: Path) -> Path:
    source = tmp_path / "source.db"
    subprocess.run(
        [sys.executable, str(FIXTURE_BUILDER), "--database", str(source)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return source


def _import_into_d1_shape(sql_text: str, target: Path) -> None:
    connection = sqlite3.connect(target)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        connection.executescript(D1_SCHEMA.read_text(encoding="utf-8"))
        connection.executescript(D1_REFERENCE_DATA.read_text(encoding="utf-8"))
        connection.executescript(sql_text)
        connection.commit()
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()


def test_historical_bootstrap_round_trip_has_exact_logical_parity(tmp_path: Path) -> None:
    source = _build_fixture(tmp_path)
    sql_path = tmp_path / "bootstrap.sql"
    manifest_path = tmp_path / "manifest.json"

    expected = write_bootstrap_package(source, sql_path, manifest_path)
    target = tmp_path / "d1.db"
    _import_into_d1_shape(sql_path.read_text(encoding="utf-8"), target)

    result = verify_database(target, expected)
    assert result["ok"] is True
    assert result["foreign_key_violations"] == 0
    assert result["logical_hash_match"] is True
    assert result["key_metrics_match"] is True
    assert result["table_mismatches"] == []

    connection = sqlite3.connect(target)
    try:
        for table in OPERATIONAL_TABLES:
            assert connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] == 0
    finally:
        connection.close()


def test_bootstrap_export_is_deterministic_for_same_snapshot(tmp_path: Path) -> None:
    source = _build_fixture(tmp_path)
    first_sql = tmp_path / "first.sql"
    first_manifest = tmp_path / "first.json"
    second_sql = tmp_path / "second.sql"
    second_manifest = tmp_path / "second.json"

    manifest_a = write_bootstrap_package(source, first_sql, first_manifest)
    manifest_b = write_bootstrap_package(source, second_sql, second_manifest)

    assert manifest_a == manifest_b
    assert first_sql.read_bytes() == second_sql.read_bytes()
    assert first_manifest.read_bytes() == second_manifest.read_bytes()


def test_bootstrap_sql_uses_reference_seed_instead_of_reinserting_identities(tmp_path: Path) -> None:
    source = _build_fixture(tmp_path)
    sql_path = tmp_path / "bootstrap.sql"
    manifest_path = tmp_path / "manifest.json"
    manifest = write_bootstrap_package(source, sql_path, manifest_path)
    sql = sql_path.read_text(encoding="utf-8")

    assert 'INSERT INTO "sources"' not in sql
    assert 'INSERT INTO "instruments"' not in sql
    for table in DATA_TABLES:
        expected_rows = manifest["tables"][table]["row_count"]
        actual_inserts = sql.count(f'INSERT INTO "{table}"')
        assert actual_inserts == expected_rows, table


def test_manifest_detects_target_tampering(tmp_path: Path) -> None:
    source = _build_fixture(tmp_path)
    sql_path = tmp_path / "bootstrap.sql"
    manifest_path = tmp_path / "manifest.json"
    expected = write_bootstrap_package(source, sql_path, manifest_path)
    target = tmp_path / "d1.db"
    _import_into_d1_shape(sql_path.read_text(encoding="utf-8"), target)

    connection = sqlite3.connect(target)
    try:
        connection.execute(
            "UPDATE nav_snapshots SET nav_per_share_nok = '999.99' WHERE nav_scope = 'FULL'"
        )
        connection.commit()
        connection.row_factory = sqlite3.Row
        actual = build_manifest(connection)
    finally:
        connection.close()

    comparison = compare_manifest(expected, actual)
    assert comparison["ok"] is False
    assert comparison["logical_hash_match"] is False
    assert comparison["key_metrics_match"] is False
    assert any(item["table"] == "nav_snapshots" for item in comparison["table_mismatches"])


def test_manifest_file_is_portable_json(tmp_path: Path) -> None:
    source = _build_fixture(tmp_path)
    sql_path = tmp_path / "bootstrap.sql"
    manifest_path = tmp_path / "manifest.json"
    expected = write_bootstrap_package(source, sql_path, manifest_path)

    loaded = load_manifest_file(manifest_path)
    assert loaded == expected
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["format_version"] == "d1-bootstrap-v1"

from __future__ import annotations

import hashlib
import json
import sqlite3
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

FORMAT_VERSION = "d1-bootstrap-v1"
LATEST_SQLITE_MIGRATION = "0029"

REFERENCE_TABLES = (
    "sources",
    "instruments",
    "bemobi_investor_facts",
    "bemobi_forward_consensus_snapshots",
    "bemobi_consensus_events",
)

DATA_TABLES = (
    "source_documents",
    "company_news",
    "market_prices",
    "market_activity",
    "fx_rates",
    "bemobi_holdings",
    "life360_holding_anchors",
    "otello_share_counts",
    "cash_anchors",
    "other_net_assets_reported_anchors",
    "other_net_assets_anchors",
    "other_net_assets_daily_estimates",
    "buyback_programs",
    "buybacks",
    "corporate_actions",
    "cash_movements",
    "buyback_daily_transactions",
    "cash_period_calibrations",
    "cash_daily_estimates",
    "nav_snapshots",
    "broker_estimate_sets",
    "broker_estimate_values",
    "consensus_snapshots",
    "provenance_records",
)

OPERATIONAL_TABLES = (
    "job_runs",
    "source_health",
    "runtime_state",
)

MANIFEST_TABLES = REFERENCE_TABLES + DATA_TABLES


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _table_columns(connection: sqlite3.Connection, table: str) -> list[str]:
    return [row["name"] for row in connection.execute(f"PRAGMA table_info({_quote(table)})")]


def _pk_columns(connection: sqlite3.Connection, table: str) -> list[str]:
    rows = connection.execute(f"PRAGMA table_info({_quote(table)})").fetchall()
    return [
        row["name"]
        for row in sorted((row for row in rows if row["pk"]), key=lambda row: row["pk"])
    ]


def _ordered_rows(connection: sqlite3.Connection, table: str) -> Iterable[sqlite3.Row]:
    pk_columns = _pk_columns(connection, table)
    if pk_columns:
        order = ", ".join(_quote(column) for column in pk_columns)
    else:
        columns = _table_columns(connection, table)
        order = ", ".join(_quote(column) for column in columns)
    yield from connection.execute(f"SELECT * FROM {_quote(table)} ORDER BY {order}")


def _canonical_value(value: Any) -> list[str]:
    if value is None:
        return ["null", ""]
    if isinstance(value, bytes):
        return ["blob", value.hex()]
    if isinstance(value, bool):
        return ["int", "1" if value else "0"]
    if isinstance(value, int):
        return ["int", str(value)]
    if isinstance(value, float):
        return ["real", repr(value)]
    return ["text", str(value)]


def _sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bytes):
        return "X'" + value.hex() + "'"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def _table_manifest(connection: sqlite3.Connection, table: str) -> dict[str, Any]:
    columns = _table_columns(connection, table)
    hasher = hashlib.sha256()
    count = 0
    hasher.update(
        json.dumps(columns, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )
    hasher.update(b"\n")
    for row in _ordered_rows(connection, table):
        canonical = [_canonical_value(row[column]) for column in columns]
        hasher.update(
            json.dumps(canonical, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
        hasher.update(b"\n")
        count += 1
    return {"columns": columns, "row_count": count, "sha256": hasher.hexdigest()}


def _decimal_sum(connection: sqlite3.Connection, table: str, column: str) -> str:
    total = Decimal("0")
    for row in connection.execute(
        f"SELECT {_quote(column)} AS value FROM {_quote(table)} WHERE {_quote(column)} IS NOT NULL"
    ):
        total += Decimal(str(row["value"]))
    return format(total, "f")


def _latest_row(
    connection: sqlite3.Connection,
    table: str,
    date_column: str,
    columns: tuple[str, ...],
    *,
    where_sql: str = "",
    parameters: tuple[Any, ...] = (),
) -> dict[str, Any] | None:
    selection = ", ".join(_quote(column) for column in columns)
    row = connection.execute(
        f"SELECT {selection} FROM {_quote(table)} {where_sql} "
        f"ORDER BY {_quote(date_column)} DESC, rowid DESC LIMIT 1",
        parameters,
    ).fetchone()
    if row is None:
        return None
    return {column: row[column] for column in columns}


def key_metrics(connection: sqlite3.Connection) -> dict[str, Any]:
    nav: dict[str, Any] = {}
    scopes = [
        row["nav_scope"]
        for row in connection.execute(
            "SELECT DISTINCT nav_scope FROM nav_snapshots ORDER BY nav_scope"
        )
    ]
    nav_columns = (
        "nav_scope", "as_of_at", "nav_total_nok", "nav_per_share_nok",
        "otec_price_nok", "discount_pct", "bemobi_value_nok", "cash_estimate_nok",
        "other_net_assets_nok", "shares_outstanding", "status", "calculation_version",
    )
    for scope in scopes:
        nav[scope] = _latest_row(
            connection, "nav_snapshots", "as_of_at", nav_columns,
            where_sql="WHERE nav_scope = ?", parameters=(scope,),
        )

    market_coverage = [
        dict(row)
        for row in connection.execute(
            """
            SELECT i.symbol, i.exchange_mic, p.price_type,
                   COUNT(*) AS row_count, MIN(p.trading_date) AS date_from,
                   MAX(p.trading_date) AS date_to,
                   MIN(p.close) AS min_price, MAX(p.close) AS max_price
            FROM market_prices p
            JOIN instruments i ON i.id = p.instrument_id
            GROUP BY i.symbol, i.exchange_mic, p.price_type
            ORDER BY i.symbol, i.exchange_mic, p.price_type
            """
        )
    ]
    market_activity_coverage = [
        dict(row)
        for row in connection.execute(
            """
            SELECT i.symbol, i.exchange_mic,
                   COUNT(*) AS row_count, MIN(a.trading_date) AS date_from,
                   MAX(a.trading_date) AS date_to,
                   SUM(CASE WHEN a.volume IS NOT NULL THEN 1 ELSE 0 END) AS volume_rows,
                   SUM(CASE WHEN a.turnover_nok IS NOT NULL THEN 1 ELSE 0 END) AS turnover_rows
            FROM market_activity a
            JOIN instruments i ON i.id = a.instrument_id
            GROUP BY i.symbol, i.exchange_mic
            ORDER BY i.symbol, i.exchange_mic
            """
        )
    ]
    fx_coverage = [
        dict(row)
        for row in connection.execute(
            """
            SELECT base_ccy, quote_ccy, rate_type,
                   COUNT(*) AS row_count, MIN(rate_date) AS date_from,
                   MAX(rate_date) AS date_to,
                   MIN(rate) AS min_rate, MAX(rate) AS max_rate
            FROM fx_rates
            GROUP BY base_ccy, quote_ccy, rate_type
            ORDER BY base_ccy, quote_ccy, rate_type
            """
        )
    ]
    share_count = _latest_row(
        connection,
        "otello_share_counts",
        "as_of_date",
        ("as_of_date", "shares_outstanding", "source_document_id", "notes"),
    )
    cash_anchor = _latest_row(
        connection,
        "cash_anchors",
        "as_of_date",
        ("as_of_date", "cash_nok", "source_document_id", "notes"),
    )
    other_net_assets_anchor = _latest_row(
        connection,
        "other_net_assets_anchors",
        "as_of_date",
        ("as_of_date", "other_net_assets_nok", "source_document_id", "notes"),
    )
    latest_buyback = _latest_row(
        connection,
        "buybacks",
        "as_of_date",
        ("as_of_date", "shares", "amount_nok", "source_document_id", "notes"),
    )
    latest_distribution = _latest_row(
        connection,
        "corporate_actions",
        "payment_date",
        (
            "external_action_id", "issuer_instrument_id", "action_type", "announcement_date",
            "record_date", "ex_date", "payment_date", "amount_per_share",
            "gross_amount_per_share", "net_amount_per_share", "gross_total_amount",
            "net_total_amount", "withholding_rate", "tax_treatment", "source_document_id",
            "notes",
        ),
        where_sql="WHERE action_type IN ('DIVIDEND', 'JCP', 'DISTRIBUTION')",
    )
    return {
        "nav": nav,
        "market_coverage": market_coverage,
        "market_activity_coverage": market_activity_coverage,
        "fx_coverage": fx_coverage,
        "share_count": share_count,
        "cash_anchor": cash_anchor,
        "other_net_assets_anchor": other_net_assets_anchor,
        "latest_buyback": latest_buyback,
        "latest_distribution": latest_distribution,
    }


def build_manifest(connection: sqlite3.Connection) -> dict[str, Any]:
    metrics = key_metrics(connection)
    return {
        "format": FORMAT_VERSION,
        "tables": {
            table: _table_manifest(connection, table)
            for table in MANIFEST_TABLES
        },
        "key_metrics": metrics,
    }


def _existing_tables(connection: sqlite3.Connection) -> set[str]:
    return {
        row["name"]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }


def validate_source(connection: sqlite3.Connection) -> dict[str, Any]:
    errors: list[str] = []
    migrations = [
        row["version"]
        for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")
    ]
    if not migrations:
        errors.append("SQLite database has no migration history")
    elif migrations[-1] != LATEST_SQLITE_MIGRATION:
        errors.append(
            f"Expected SQLite migration {LATEST_SQLITE_MIGRATION}, found {migrations[-1]!r}"
        )
    missing_tables = [table for table in MANIFEST_TABLES if table not in _existing_tables(connection)]
    if missing_tables:
        errors.append(f"Missing manifest tables: {', '.join(missing_tables)}")

    expected_scopes = {"FULL", "ESTIMATED"}
    actual_scopes = {
        row["nav_scope"]
        for row in connection.execute("SELECT DISTINCT nav_scope FROM nav_snapshots")
    }
    if actual_scopes and not expected_scopes.issubset(actual_scopes):
        errors.append(
            f"NAV scope coverage incomplete: expected {sorted(expected_scopes)}, got {sorted(actual_scopes)}"
        )

    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        errors.append(f"SQLite integrity_check failed: {integrity}")
    return {"ok": not errors, "errors": errors}


def build_sql(connection: sqlite3.Connection, manifest: dict[str, Any]) -> str:
    lines = [
        "-- Generated by backend/app/db/d1_bootstrap.py",
        "PRAGMA foreign_keys = OFF;",
        "BEGIN TRANSACTION;",
    ]
    for table in MANIFEST_TABLES:
        columns = _table_columns(connection, table)
        column_sql = ", ".join(_quote(column) for column in columns)
        for row in _ordered_rows(connection, table):
            values = ", ".join(_sql_literal(row[column]) for column in columns)
            lines.append(
                f"INSERT INTO {_quote(table)} ({column_sql}) VALUES ({values});"
            )
    lines.extend(("COMMIT;", "PRAGMA foreign_keys = ON;", ""))
    return "\n".join(lines)


def compare_manifests(expected: dict[str, Any], actual: dict[str, Any]) -> dict[str, Any]:
    mismatches: list[dict[str, Any]] = []
    for table in MANIFEST_TABLES:
        expected_table = expected.get("tables", {}).get(table)
        actual_table = actual.get("tables", {}).get(table)
        if expected_table != actual_table:
            mismatches.append(
                {"table": table, "expected": expected_table, "actual": actual_table}
            )
    if expected.get("key_metrics") != actual.get("key_metrics"):
        mismatches.append(
            {
                "key_metrics": True,
                "expected": expected.get("key_metrics"),
                "actual": actual.get("key_metrics"),
            }
        )
    return {"ok": not mismatches, "mismatches": mismatches}


def compare_manifest(expected: dict[str, Any], actual: dict[str, Any]) -> dict[str, Any]:
    return compare_manifests(expected, actual)


def _open_database(path: Path, *, read_only: bool) -> sqlite3.Connection:
    if read_only:
        uri = f"file:{path.resolve().as_posix()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
    else:
        connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    if read_only:
        connection.execute("PRAGMA query_only = ON")
    return connection


def resolve_d1_local_database(path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_file():
        return candidate
    if not candidate.is_dir():
        raise FileNotFoundError(candidate)

    matches: list[Path] = []
    for file_path in candidate.rglob("*"):
        if not file_path.is_file():
            continue
        try:
            connection = _open_database(file_path, read_only=True)
            try:
                tables = _existing_tables(connection)
                if {"sources", "instruments", "nav_snapshots"}.issubset(tables):
                    matches.append(file_path)
            finally:
                connection.close()
        except sqlite3.DatabaseError:
            continue
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected exactly one local D1 SQLite database below {candidate}, found {len(matches)}"
        )
    return matches[0]


def write_bootstrap_package(
    database_path: str | Path,
    sql_path: str | Path,
    manifest_path: str | Path,
) -> dict[str, Any]:
    source_path = Path(database_path)
    sql_output = Path(sql_path)
    manifest_output = Path(manifest_path)
    sql_output.parent.mkdir(parents=True, exist_ok=True)
    manifest_output.parent.mkdir(parents=True, exist_ok=True)

    connection = _open_database(source_path, read_only=True)
    try:
        connection.execute("BEGIN")
        validation = validate_source(connection)
        if not validation["ok"]:
            raise RuntimeError("; ".join(validation["errors"]))
        manifest = build_manifest(connection)
        sql = build_sql(connection, manifest)
        connection.rollback()
    finally:
        connection.close()

    sql_tmp = sql_output.with_suffix(sql_output.suffix + ".tmp")
    manifest_tmp = manifest_output.with_suffix(manifest_output.suffix + ".tmp")
    sql_tmp.write_text(sql, encoding="utf-8")
    manifest_tmp.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    sql_tmp.replace(sql_output)
    manifest_tmp.replace(manifest_output)
    return manifest


def compare_manifest(expected: dict[str, Any], actual: dict[str, Any]) -> dict[str, Any]:
    mismatches: list[dict[str, Any]] = []
    for table in MANIFEST_TABLES:
        expected_table = expected.get("tables", {}).get(table)
        actual_table = actual.get("tables", {}).get(table)
        if expected_table != actual_table:
            mismatches.append(
                {"table": table, "expected": expected_table, "actual": actual_table}
            )
    if expected.get("key_metrics") != actual.get("key_metrics"):
        mismatches.append(
            {
                "key_metrics": True,
                "expected": expected.get("key_metrics"),
                "actual": actual.get("key_metrics"),
            }
        )
    return {"ok": not mismatches, "mismatches": mismatches}

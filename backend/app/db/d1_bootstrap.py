from __future__ import annotations

import hashlib
import json
import sqlite3
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

FORMAT_VERSION = "d1-bootstrap-v1"
LATEST_SQLITE_MIGRATION = "0025"

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
                   MAX(p.trading_date) AS date_to
            FROM market_prices p
            JOIN instruments i ON i.id = p.instrument_id
            GROUP BY i.symbol, i.exchange_mic, p.price_type
            ORDER BY i.symbol, i.exchange_mic, p.price_type
            """
        )
    ]
    fx_coverage = [
        dict(row)
        for row in connection.execute(
            """
            SELECT base_currency, quote_currency, COUNT(*) AS row_count,
                   MIN(observed_at) AS observed_from, MAX(observed_at) AS observed_to
            FROM fx_rates
            GROUP BY base_currency, quote_currency
            ORDER BY base_currency, quote_currency
            """
        )
    ]

    return {
        "nav_latest": nav,
        "market_coverage": market_coverage,
        "fx_coverage": fx_coverage,
        "buybacks": {
            "row_count": connection.execute("SELECT COUNT(*) FROM buybacks").fetchone()[0],
            "shares": connection.execute("SELECT COALESCE(SUM(shares), 0) FROM buybacks").fetchone()[0],
            "amount_nok": _decimal_sum(connection, "buybacks", "amount_nok"),
            "date_from": connection.execute("SELECT MIN(trade_date) FROM buybacks").fetchone()[0],
            "date_to": connection.execute("SELECT MAX(trade_date) FROM buybacks").fetchone()[0],
        },
        "buyback_daily": {
            "row_count": connection.execute("SELECT COUNT(*) FROM buyback_daily_transactions").fetchone()[0],
            "shares": connection.execute("SELECT COALESCE(SUM(shares), 0) FROM buyback_daily_transactions").fetchone()[0],
            "amount_nok": _decimal_sum(connection, "buyback_daily_transactions", "amount_nok"),
        },
        "cash_latest": _latest_row(
            connection, "cash_daily_estimates", "estimate_date",
            ("estimate_date", "cash_nok", "quality", "inputs_hash"),
        ),
        "ona_latest": _latest_row(
            connection, "other_net_assets_daily_estimates", "estimate_date",
            (
                "estimate_date", "amount_usd", "usd_nok_rate", "amount_nok",
                "base_amount_nok", "associated_receivable_nok", "option_liability_nok",
                "option_quality", "quality", "inputs_hash",
            ),
        ),
        "share_count_latest": _latest_row(
            connection, "otello_share_counts", "effective_from",
            ("effective_from", "total_shares", "treasury_shares", "outstanding_shares"),
        ),
        "bemobi_holding_latest": _latest_row(
            connection, "bemobi_holdings", "effective_from",
            ("effective_from", "effective_to", "shares", "ownership_pct"),
        ),
    }


def _existing_tables(connection: sqlite3.Connection) -> set[str]:
    return {
        row["name"]
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }


def validate_source(connection: sqlite3.Connection) -> dict[str, Any]:
    integrity_rows = [row[0] for row in connection.execute("PRAGMA integrity_check")]
    foreign_key_rows = [tuple(row) for row in connection.execute("PRAGMA foreign_key_check")]
    existing = _existing_tables(connection)
    missing = sorted(set(MANIFEST_TABLES) - existing)

    latest = None
    if "schema_migrations" in existing:
        row = connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1"
        ).fetchone()
        latest = row[0] if row else None

    errors: list[str] = []
    if integrity_rows != ["ok"]:
        errors.append(f"SQLite integrity_check failed: {integrity_rows!r}")
    if foreign_key_rows:
        errors.append(f"SQLite foreign_key_check found {len(foreign_key_rows)} violation(s)")
    if missing:
        errors.append(f"Missing bootstrap table(s): {', '.join(missing)}")
    if latest != LATEST_SQLITE_MIGRATION:
        errors.append(f"Expected SQLite migration {LATEST_SQLITE_MIGRATION}, found {latest!r}")

    return {
        "ok": not errors,
        "latest_migration": latest,
        "integrity_check": integrity_rows,
        "foreign_key_violations": len(foreign_key_rows),
        "missing_tables": missing,
        "errors": errors,
    }


def build_manifest(connection: sqlite3.Connection) -> dict[str, Any]:
    tables = {table: _table_manifest(connection, table) for table in MANIFEST_TABLES}
    global_hasher = hashlib.sha256()
    for table in MANIFEST_TABLES:
        item = tables[table]
        global_hasher.update(f"{table}\0{item['row_count']}\0{item['sha256']}\n".encode("utf-8"))

    return {
        "format_version": FORMAT_VERSION,
        "latest_sqlite_migration": LATEST_SQLITE_MIGRATION,
        "reference_tables": list(REFERENCE_TABLES),
        "exported_tables": list(DATA_TABLES),
        "omitted_operational_tables": list(OPERATIONAL_TABLES),
        "tables": tables,
        "logical_sha256": global_hasher.hexdigest(),
        "key_metrics": key_metrics(connection),
    }


def build_sql(connection: sqlite3.Connection, manifest: dict[str, Any]) -> str:
    lines = [
        "-- GENERATED D1 HISTORICAL BOOTSTRAP. Do not edit by hand.",
        f"-- format: {FORMAT_VERSION}",
        f"-- logical_sha256: {manifest['logical_sha256']}",
        "-- Apply only after the Cloudflare schema/reference migrations on an otherwise fresh D1 database.",
        "PRAGMA foreign_keys = ON;",
        "PRAGMA defer_foreign_keys = ON;",
        "",
    ]

    for table in DATA_TABLES:
        columns = _table_columns(connection, table)
        quoted_columns = ", ".join(_quote(column) for column in columns)
        rows_written = 0
        lines.append(f"-- {table}")
        for row in _ordered_rows(connection, table):
            values = ", ".join(_sql_literal(row[column]) for column in columns)
            lines.append(f"INSERT INTO {_quote(table)} ({quoted_columns}) VALUES ({values});")
            rows_written += 1
        if rows_written == 0:
            lines.append("-- empty")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


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
            mismatches.append({"table": table, "expected": expected_table, "actual": actual_table})

    key_metrics_match = expected.get("key_metrics") == actual.get("key_metrics")
    logical_hash_match = expected.get("logical_sha256") == actual.get("logical_sha256")
    return {
        "ok": not mismatches and key_metrics_match and logical_hash_match,
        "logical_hash_match": logical_hash_match,
        "key_metrics_match": key_metrics_match,
        "table_mismatches": mismatches,
    }


def verify_database(database_path: str | Path, expected_manifest: dict[str, Any]) -> dict[str, Any]:
    path = Path(database_path)
    connection = _open_database(path, read_only=True)
    try:
        foreign_key_rows = [tuple(row) for row in connection.execute("PRAGMA foreign_key_check")]
        actual = build_manifest(connection)
    finally:
        connection.close()
    comparison = compare_manifest(expected_manifest, actual)
    comparison["foreign_key_violations"] = len(foreign_key_rows)
    comparison["ok"] = comparison["ok"] and not foreign_key_rows
    return comparison


def load_manifest_file(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))

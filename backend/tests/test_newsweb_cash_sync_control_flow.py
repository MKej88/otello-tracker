"""Risikobaserte tester av kontrollflyten i NewsWeb-kontantsynk."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pytest

from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.db.repository import create_source_document
from app.newsweb.cash_sync import sync_newsweb_daily_buyback_cash
from app.newsweb import cash_sync


def _seed_week(
    database_path: str,
    *,
    weekly_shares: int = 100,
    daily_rows: tuple[tuple[str, int, str, str], ...] = (
        ("2026-08-28", 100, "1720.00", "CONFIRMED"),
    ),
) -> int:
    """Lag den minste realistiske uken som kontantsynken trenger."""
    with get_connection(database_path) as connection:
        source_id = create_source_document(
            connection,
            source_code="NEWSWEB",
            external_id="cash-sync-test",
            document_type="REGULATORY_NEWS",
            title="Kontantsynk-test",
            url="https://example.invalid/message/1",
        )
        program_id = connection.execute(
            """
            INSERT INTO buyback_programs(
                external_program_id, announced_at, start_date, max_shares,
                status, source_document_id
            ) VALUES ('cash-sync-program', '2026-08-01T00:00:00Z',
                      '2026-08-01', 1000000, 'ACTIVE', ?)
            """,
            (source_id,),
        ).lastrowid
        buyback_id = connection.execute(
            """
            INSERT INTO buybacks(
                program_id, trade_date, shares, avg_price_nok, amount_nok,
                cumulative_program_shares, treasury_shares_after,
                source_document_id
            ) VALUES (?, '2026-08-28', ?, '17.20', '1720.00', ?, 1000100, ?)
            """,
            (program_id, weekly_shares, weekly_shares, source_id),
        ).lastrowid
        connection.execute(
            """
            INSERT INTO cash_movements(
                movement_date, movement_type, amount_nok, currency,
                description, confidence, buyback_id
            ) VALUES ('2026-08-28', 'OTELLO_BUYBACK', '-1720.00', 'NOK',
                      'Ukentlig sikkerhetsnett', 'CONFIRMED', ?)
            """,
            (buyback_id,),
        )
        for trade_date, shares, amount_nok, quality in daily_rows:
            connection.execute(
                """
                INSERT INTO buyback_daily_transactions(
                    weekly_buyback_id, trade_date, shares, avg_price_nok,
                    amount_nok, trade_count, source_document_id, quality
                ) VALUES (?, ?, ?, '17.20', ?, 1, ?, ?)
                """,
                (buyback_id, trade_date, shares, amount_nok, source_id, quality),
            )
        connection.commit()
    assert buyback_id is not None
    return buyback_id


def _cash_rows(database_path: str) -> list[sqlite3.Row]:
    with get_connection(database_path) as connection:
        return connection.execute("""
            SELECT movement_date, movement_type, amount_nok
            FROM cash_movements
            ORDER BY movement_date, id
            """).fetchall()


def test_avviser_delvis_uke_uten_aa_fjerne_ukentlig_sikkerhetsnett(
    tmp_path: Path,
) -> None:
    """Viktigst: delvise API-data må aldri redusere bokført tilbakekjøp."""
    database_path = str(tmp_path / "delvis-uke.db")
    init_database(database_path)
    buyback_id = _seed_week(database_path, weekly_shares=101)

    with pytest.raises(ValueError, match="daglige aksjer 100 != uke 101"):
        sync_newsweb_daily_buyback_cash(
            database_path,
            weekly_buyback_id=buyback_id,
        )

    rows = _cash_rows(database_path)
    assert [(row["movement_type"], row["amount_nok"]) for row in rows] == [
        ("OTELLO_BUYBACK", "-1720.00")
    ]


def test_avviser_rad_som_krever_kontroll_uten_delvis_lagring(
    tmp_path: Path,
) -> None:
    """Nest viktigst: usikre data skal ikke erstatte bekreftet ukesbeløp."""
    database_path = str(tmp_path / "krever-kontroll.db")
    init_database(database_path)
    buyback_id = _seed_week(
        database_path,
        daily_rows=(("2026-08-28", 100, "1720.00", "REQUIRES_REVIEW"),),
    )

    with pytest.raises(ValueError, match="daglig rad krever kontroll"):
        sync_newsweb_daily_buyback_cash(
            database_path,
            weekly_buyback_id=buyback_id,
        )

    assert [row["movement_type"] for row in _cash_rows(database_path)] == [
        "OTELLO_BUYBACK"
    ]


def test_retry_oppdaterer_eksisterende_rad_uten_duplikat_og_rydder_gammel_dato(
    tmp_path: Path,
) -> None:
    """Tredje viktigst: retry skal gi samme fasit, også etter et eldre resultat."""
    database_path = str(tmp_path / "retry.db")
    init_database(database_path)
    buyback_id = _seed_week(database_path)

    with get_connection(database_path) as connection:
        connection.executemany(
            """
            INSERT INTO cash_movements(
                movement_date, movement_type, amount_nok, currency,
                description, confidence, buyback_id
            ) VALUES (?, 'OTELLO_BUYBACK_DAILY', ?, 'NOK', 'Gammel verdi',
                      'CONFIRMED', ?)
            """,
            (
                ("2026-08-28", "-1700", buyback_id),
                ("2026-08-27", "-20", buyback_id),
            ),
        )
        connection.commit()

    first = sync_newsweb_daily_buyback_cash(
        database_path,
        weekly_buyback_id=buyback_id,
    )
    second = sync_newsweb_daily_buyback_cash(
        database_path,
        weekly_buyback_id=buyback_id,
    )

    assert first["daily_cash_rows_updated"] == 1
    assert second["daily_cash_rows_written"] == 0
    assert second["daily_cash_rows_updated"] == 0
    rows = _cash_rows(database_path)
    assert [
        (row["movement_date"], row["movement_type"], row["amount_nok"]) for row in rows
    ] == [("2026-08-28", "OTELLO_BUYBACK_DAILY", "-1720.00")]


def test_kontantsynk_henter_alle_rader_med_to_select_sporringer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Antall lesinger skal ikke vokse med antall daglige transaksjoner."""
    database_path = str(tmp_path / "query-count.db")
    init_database(database_path)
    buyback_id = _seed_week(
        database_path,
        weekly_shares=100,
        daily_rows=(
            ("2026-08-24", 20, "344.00", "CONFIRMED"),
            ("2026-08-25", 20, "344.00", "CONFIRMED"),
            ("2026-08-26", 20, "344.00", "CONFIRMED"),
            ("2026-08-27", 20, "344.00", "CONFIRMED"),
            ("2026-08-28", 20, "344.00", "CONFIRMED"),
        ),
    )
    statements: list[str] = []

    @contextmanager
    def traced_connection(path: str | None = None) -> Iterator[sqlite3.Connection]:
        with get_connection(path) as connection:
            connection.set_trace_callback(statements.append)
            yield connection

    monkeypatch.setattr(cash_sync, "get_connection", traced_connection)

    result = sync_newsweb_daily_buyback_cash(
        database_path, weekly_buyback_id=buyback_id
    )

    selects = [
        statement for statement in statements if statement.lstrip().startswith("SELECT")
    ]
    assert len(selects) == 2
    assert result["daily_cash_rows_written"] == 5


def test_kontantsynk_skriver_ikke_uendrede_rader_pa_nytt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = str(tmp_path / "unchanged.db")
    init_database(database_path)
    buyback_id = _seed_week(database_path)
    sync_newsweb_daily_buyback_cash(database_path, weekly_buyback_id=buyback_id)
    statements: list[str] = []

    @contextmanager
    def traced_connection(path: str | None = None) -> Iterator[sqlite3.Connection]:
        with get_connection(path) as connection:
            connection.set_trace_callback(statements.append)
            yield connection

    monkeypatch.setattr(cash_sync, "get_connection", traced_connection)

    result = sync_newsweb_daily_buyback_cash(
        database_path, weekly_buyback_id=buyback_id
    )

    updates = [
        statement
        for statement in statements
        if statement.lstrip().startswith("UPDATE cash_movements")
    ]
    assert updates == []
    assert result["daily_cash_rows_updated"] == 0

from __future__ import annotations

from pathlib import Path

from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.nav.cash_curve import _nearest_fx as nearest_cash_fx
from app.nav.daily_nav import _nearest_fx
from app.nav.other_net_assets import _nearest_fx as nearest_other_net_assets_fx


def _source_id(connection, code: str) -> int:
    row = connection.execute("SELECT id FROM sources WHERE code=?", (code,)).fetchone()
    assert row is not None
    return int(row["id"])


def _insert_fx(connection, *, source_id: int, day: str, rate: str) -> None:
    connection.execute(
        """
        INSERT INTO fx_rates(
            base_currency, quote_currency, observed_at, rate, source_id
        ) VALUES ('BRL', 'NOK', ?, ?, ?)
        """,
        (f"{day}T00:00:00Z", rate, source_id),
    )


def test_norges_bank_wins_over_ecb_on_same_date(tmp_path: Path) -> None:
    database = str(tmp_path / "fx-priority.db")
    init_database(database)

    with get_connection(database) as connection:
        ecb = _source_id(connection, "ECB")
        norges_bank = _source_id(connection, "NORGES_BANK")
        _insert_fx(connection, source_id=ecb, day="2026-08-18", rate="1.70")
        _insert_fx(connection, source_id=norges_bank, day="2026-08-18", rate="1.90")
        connection.commit()

        selected = _nearest_fx(connection, "BRL", "2026-08-18")
        assert selected is not None
        assert selected["source_code"] == "NORGES_BANK"
        assert selected["rate"] == "1.90"


def test_newer_fallback_date_wins_over_older_norges_bank(tmp_path: Path) -> None:
    database = str(tmp_path / "fx-freshness.db")
    init_database(database)

    with get_connection(database) as connection:
        ecb = _source_id(connection, "ECB")
        norges_bank = _source_id(connection, "NORGES_BANK")
        _insert_fx(connection, source_id=norges_bank, day="2026-08-18", rate="1.90")
        _insert_fx(connection, source_id=ecb, day="2026-08-19", rate="1.75")
        connection.commit()

        selected = _nearest_fx(connection, "BRL", "2026-08-19")
        assert selected is not None
        assert selected["source_code"] == "ECB"
        assert selected["rate_date"] == "2026-08-19"
        assert selected["rate"] == "1.75"


def test_all_nav_components_use_same_source_priority(tmp_path: Path) -> None:
    database = str(tmp_path / "fx-component-priority.db")
    init_database(database)

    with get_connection(database) as connection:
        ecb = _source_id(connection, "ECB")
        norges_bank = _source_id(connection, "NORGES_BANK")
        _insert_fx(connection, source_id=norges_bank, day="2026-08-18", rate="1.90")
        _insert_fx(connection, source_id=ecb, day="2026-08-18", rate="1.70")
        connection.commit()

        selections = (
            _nearest_fx(connection, "BRL", "2026-08-18"),
            nearest_cash_fx(connection, "BRL", "2026-08-18"),
            nearest_other_net_assets_fx(connection, "BRL", "2026-08-18"),
        )

        assert all(selected is not None for selected in selections)
        assert {selected["source_code"] for selected in selections} == {"NORGES_BANK"}
        assert {selected["rate"] for selected in selections} == {"1.90"}

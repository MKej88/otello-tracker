from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.history import seed_curated_history
from app.jobs import bootstrap_production as bootstrap
from app.jobs.preflight import cash_anchor_fx_gaps, run_preflight


def _source_id(connection, code: str) -> int:
    return int(connection.execute("SELECT id FROM sources WHERE code=?", (code,)).fetchone()["id"])


def test_preflight_missing_database_is_not_ready(tmp_path) -> None:
    database = str(tmp_path / "missing.db")
    result = run_preflight(database, target_date="2026-08-17")
    assert result["ready"] is False
    assert result["blockers"][0]["name"] == "database_exists"


def test_seed_only_database_exposes_historical_data_blockers(tmp_path) -> None:
    database = str(tmp_path / "seed-only.db")
    init_database(database)
    seed_curated_history(database)

    result = run_preflight(database, target_date="2026-08-17", check_derived=False)
    blockers = {item["name"] for item in result["blockers"]}
    assert "otec_historical_prices" in blockers
    assert "bmob3_historical_prices" in blockers
    assert "brl_nok_historical_fx" in blockers
    assert "cash_anchor_fx_windows" in blockers
    assert result["ready"] is False


def test_cash_anchor_fx_gaps_require_historical_usd_rates(tmp_path) -> None:
    database = str(tmp_path / "cash-fx.db")
    init_database(database)
    seed_curated_history(database)

    with get_connection(database) as connection:
        missing_before = cash_anchor_fx_gaps(connection)
        assert missing_before
        ecb_id = _source_id(connection, "ECB")
        anchors = connection.execute(
            """
            SELECT as_of_date, reported_currency
            FROM cash_anchors
            WHERE anchor_type='REPORTED' AND reported_currency <> 'NOK'
            ORDER BY as_of_date
            """
        ).fetchall()
        for anchor in anchors:
            connection.execute(
                """
                INSERT OR REPLACE INTO fx_rates(
                    base_currency, quote_currency, observed_at, rate, source_id
                ) VALUES (?, 'NOK', ?, '10', ?)
                """,
                (anchor["reported_currency"], f"{anchor['as_of_date']}T16:00:00Z", ecb_id),
            )
        connection.commit()
        assert cash_anchor_fx_gaps(connection) == []


def test_bootstrap_fetches_full_ecb_and_every_b3_year(monkeypatch, tmp_path) -> None:
    database = str(tmp_path / "bootstrap.db")
    calls: dict[str, object] = {"b3": []}

    def fake_fetch_ecb(start: str, end: str):
        calls["ecb"] = (start, end)
        return "https://example.invalid/ecb.csv", "dummy"

    def fake_download_b3(year: int) -> bytes:
        calls["b3"].append(year)
        return b"dummy"

    monkeypatch.setattr(bootstrap, "fetch_ecb_csv", fake_fetch_ecb)
    monkeypatch.setattr(bootstrap, "import_ecb_fx_csv", lambda *args, **kwargs: 123)
    monkeypatch.setattr(bootstrap, "download_cotahist_year", fake_download_b3)
    monkeypatch.setattr(bootstrap, "import_b3_bmob3_zip", lambda *args, **kwargs: 250)
    monkeypatch.setattr(bootstrap, "run_refresh", lambda *args, **kwargs: {"status": "ok"})
    monkeypatch.setattr(
        bootstrap,
        "run_preflight",
        lambda *args, **kwargs: {"ready": True, "status": "READY", "blockers": []},
    )

    result = bootstrap.run_bootstrap(
        database,
        target_date="2026-08-17",
        history_start="2021-02-10",
        b3_start_year=2021,
    )

    assert calls["ecb"] == ("2021-02-10", "2026-08-17")
    assert calls["b3"] == [2021, 2022, 2023, 2024, 2025, 2026]
    assert result["ready"] is True
    assert result["status"] == "READY"

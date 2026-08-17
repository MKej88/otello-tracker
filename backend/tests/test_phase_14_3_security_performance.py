import csv
import io
import zipfile
from decimal import Decimal

import pytest

import app.bemobi.cvm_refresh as cvm_refresh
import app.nav.cash_refresh as cash_refresh
import app.nav.intraday as intraday
from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.db.runtime_state import get_runtime_state, set_runtime_state
from app.history import seed_curated_history_if_needed
from app.marketdata.euronext_delayed import OTEC_ISIN, import_delayed_otec_trade
from app.newsweb.client import MAX_ATTACHMENT_BYTES, MAX_JSON_BYTES, _bounded_read


class FakeResponse:
    def __init__(self, payload: bytes, content_length: str | None = None):
        self.payload = payload
        self.headers = {}
        if content_length is not None:
            self.headers["Content-Length"] = content_length

    def read(self, size: int = -1) -> bytes:
        return self.payload if size < 0 else self.payload[:size]


def _euronext_payload(*, timestamp: str, publication: str, price: str, trade_id: str) -> bytes:
    header = [
        "TradingDateTime",
        "PublicationDateTime",
        "MifidInstrumentID",
        "MifidPrice",
        "MifidQuantity",
        "MifidPriceNotation",
        "MifidCurrency",
        "Venue",
        "TradeUniqueIdentifier",
        "MissingPrice",
        "VenueOfPublication",
    ]
    text = io.StringIO()
    text.write("Euronext delayed-data terms\n")
    writer = csv.DictWriter(text, fieldnames=header, lineterminator="\n")
    writer.writeheader()
    writer.writerow(
        {
            "TradingDateTime": timestamp,
            "PublicationDateTime": publication,
            "MifidInstrumentID": OTEC_ISIN,
            "MifidPrice": price,
            "MifidQuantity": "100",
            "MifidPriceNotation": "MONE",
            "MifidCurrency": "NOK",
            "Venue": "XOSL",
            "TradeUniqueIdentifier": trade_id,
            "MissingPrice": "",
            "VenueOfPublication": "XOSL",
        }
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("Trades_Equities.csv", text.getvalue().encode("utf-8"))
    return buffer.getvalue()


def test_runtime_state_and_curated_seed_become_noop_when_manifests_are_unchanged(tmp_path) -> None:
    database = str(tmp_path / "state.db")
    init_database(database)

    first = seed_curated_history_if_needed(database)
    second = seed_curated_history_if_needed(database)

    assert first.get("skipped") is not True
    assert second["skipped"] is True
    assert second["reason"] == "curated_manifests_unchanged"
    assert get_runtime_state("curated_seed_fingerprint", database) == second["fingerprint"]


def test_cash_dirty_check_skips_full_rebuild_when_inputs_and_horizon_are_unchanged(
    tmp_path, monkeypatch
) -> None:
    database = str(tmp_path / "cash-skip.db")
    init_database(database)
    set_runtime_state("cash_curve_input_signature_v1", "stable", database)
    with get_connection(database) as connection:
        connection.execute(
            """
            INSERT INTO cash_daily_estimates(
                estimate_date, cash_nok, quality, inputs_hash, notes
            ) VALUES ('2026-08-17', '100', 'FORECAST_PARTIAL', 'x', 'test')
            """
        )
        connection.commit()

    monkeypatch.setattr(cash_refresh, "cash_input_signature", lambda *_args, **_kwargs: "stable")
    monkeypatch.setattr(
        cash_refresh,
        "rebuild_daily_cash",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("full cash rebuild should have been skipped")
        ),
    )

    result = cash_refresh.rebuild_daily_cash_if_changed(
        database,
        end_date="2026-08-17",
    )
    assert result["skipped"] is True
    assert result["reason"] == "cash_inputs_unchanged"


def test_cash_dirty_check_rebuilds_and_updates_signature_when_inputs_change(
    tmp_path, monkeypatch
) -> None:
    database = str(tmp_path / "cash-change.db")
    init_database(database)
    set_runtime_state("cash_curve_input_signature_v1", "old", database)
    signatures = iter(["new-before", "new-after"])
    monkeypatch.setattr(
        cash_refresh,
        "cash_input_signature",
        lambda *_args, **_kwargs: next(signatures),
    )
    monkeypatch.setattr(
        cash_refresh,
        "rebuild_daily_cash",
        lambda *_args, **_kwargs: {"written": 10, "to": "2026-08-17"},
    )

    result = cash_refresh.rebuild_daily_cash_if_changed(
        database,
        end_date="2026-08-17",
    )

    assert result["skipped"] is False
    assert result["input_signature"] == "new-after"
    assert get_runtime_state("cash_curve_input_signature_v1", database) == "new-after"


def test_incremental_cvm_refresh_marks_historical_year_complete_but_keeps_current_rolling(
    tmp_path, monkeypatch
) -> None:
    database = str(tmp_path / "cvm.db")
    init_database(database)
    calls: list[list[int]] = []

    monkeypatch.setattr(cvm_refresh, "years_for_refresh", lambda *_args, **_kwargs: [2025, 2026])

    def collect(*_args, **kwargs):
        calls.append(list(kwargs["years"]))
        return {"years": list(kwargs["years"]), "archived": 1, "errors": []}

    monkeypatch.setattr(cvm_refresh, "collect_bemobi_cvm_news", collect)

    first = cvm_refresh.collect_bemobi_cvm_news_incremental(database, target_year=2026)
    second = cvm_refresh.collect_bemobi_cvm_news_incremental(database, target_year=2026)

    assert calls == [[2025, 2026], [2026]]
    assert first["historical_years_marked_complete"] == [2025]
    assert second["historical_years_marked_complete"] == []
    assert get_runtime_state("cvm_ipe_historical_complete:2025", database) == "complete"


def test_newsweb_bounded_read_rejects_oversized_content_length_and_stream() -> None:
    with pytest.raises(ValueError, match="størrelsesgrense"):
        _bounded_read(
            FakeResponse(b"{}", content_length=str(MAX_JSON_BYTES + 1)),
            MAX_JSON_BYTES,
            label="NewsWeb JSON-respons",
        )

    with pytest.raises(ValueError, match="størrelsesgrense"):
        _bounded_read(
            FakeResponse(b"x" * (MAX_ATTACHMENT_BYTES + 1)),
            MAX_ATTACHMENT_BYTES,
            label="NewsWeb attachment",
        )


def test_otec_delayed_payloads_keep_immutable_source_documents(tmp_path) -> None:
    database = str(tmp_path / "otec-provenance.db")
    init_database(database)
    first = _euronext_payload(
        timestamp="2026-08-17T08:00:00.000000Z",
        publication="2026-08-17T08:00:01.000000Z",
        price="17.20",
        trade_id="OTEC-1",
    )
    second = _euronext_payload(
        timestamp="2026-08-17T10:00:00.000000Z",
        publication="2026-08-17T10:00:01.000000Z",
        price="17.40",
        trade_id="OTEC-2",
    )

    import_delayed_otec_trade(
        first,
        time_selection="LAST_HOUR",
        source_url="https://example/last-hour",
        database_path=database,
    )
    import_delayed_otec_trade(
        second,
        time_selection="LAST_HOUR",
        source_url="https://example/last-hour",
        database_path=database,
    )
    # Identical retry must remain idempotent.
    import_delayed_otec_trade(
        second,
        time_selection="LAST_HOUR",
        source_url="https://example/last-hour",
        database_path=database,
    )

    with get_connection(database) as connection:
        documents = connection.execute(
            """
            SELECT sd.id, sd.external_id, sd.content_sha256
            FROM source_documents sd
            JOIN sources s ON s.id=sd.source_id
            WHERE s.code='EURONEXT'
              AND sd.external_id LIKE 'otec-delayed-last_hour-2026-08-17-%'
            ORDER BY sd.id
            """
        ).fetchall()
        prices = connection.execute(
            """
            SELECT mp.price, mp.source_document_id
            FROM market_prices mp
            JOIN instruments i ON i.id=mp.instrument_id
            WHERE i.symbol='OTEC' AND mp.price_type='LAST'
            ORDER BY mp.observed_at
            """
        ).fetchall()

    assert len(documents) == 2
    assert documents[0]["content_sha256"] != documents[1]["content_sha256"]
    assert [Decimal(row["price"]) for row in prices] == [Decimal("17.20"), Decimal("17.40")]
    assert prices[0]["source_document_id"] != prices[1]["source_document_id"]


def test_explicit_intraday_core_snapshot_persists_requested_calendar_date(tmp_path, monkeypatch) -> None:
    database = str(tmp_path / "intraday-nav.db")
    init_database(database)
    monkeypatch.setattr(
        intraday,
        "calculate_daily_core_nav",
        lambda _connection, as_of_date: {
            "as_of_date": as_of_date,
            "ready": True,
            "nav_total_nok": Decimal("1000"),
            "nav_per_share_nok": Decimal("10"),
            "otec_price_nok": Decimal("8"),
            "discount_pct": Decimal("20"),
            "bemobi_value_nok": Decimal("800"),
            "cash_nok": Decimal("200"),
            "other_net_assets_nok": Decimal("0"),
            "shares_outstanding": 100,
            "status": "BACKFILLED",
            "components": {
                "scope": "CORE",
                "as_of_date": as_of_date,
                "otec": {"price_date": "2026-08-14"},
                "bmob3": {"price_date": as_of_date},
            },
            "inputs_hash": "hash",
            "quality_notes": "test",
        },
    )

    result = intraday.rebuild_core_nav_for_date(database, as_of_date="2026-08-17")
    with get_connection(database) as connection:
        row = connection.execute(
            "SELECT as_of_at, nav_per_share_nok FROM nav_snapshots ORDER BY id DESC LIMIT 1"
        ).fetchone()

    assert result["written"] == 1
    assert result["indicative_calendar_date"] is True
    assert row["as_of_at"] == "2026-08-17T23:59:59Z"
    assert Decimal(row["nav_per_share_nok"]) == Decimal("10")

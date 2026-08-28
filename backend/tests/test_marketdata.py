from decimal import Decimal
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.history import seed_curated_history
from app.marketdata.b3_cotahist import parse_cotahist_line
from app.marketdata.backfill import (
    import_b3_bmob3_zip,
    import_ecb_fx_csv,
    import_euronext_otec_csv,
    import_investing_otec_csv,
    market_data_status,
)
from app.marketdata.ecb_fx import derive_nok_cross_rates, parse_ecb_csv
from app.marketdata.euronext_csv import parse_euronext_historical_csv
from app.marketdata.investing_csv import (
    parse_investing_historical_csv,
    reconstruct_otec_2022_distribution,
)
from app.nav.core_nav import rebuild_core_nav_anchors


def _put(chars: list[str], start: int, end: int, value: str) -> None:
    width = end - start
    chars[start:end] = list(value.ljust(width)[:width])


def _b3_line(
    *,
    trading_date: str = "20251230",
    ticker: str = "BMOB3",
    close_cents: int = 3000,
) -> str:
    chars = list(" " * 245)
    _put(chars, 0, 2, "01")
    _put(chars, 2, 10, trading_date)
    _put(chars, 10, 12, "02")
    _put(chars, 12, 24, ticker)
    _put(chars, 24, 27, "010")
    _put(chars, 27, 39, "BEMOBI")
    _put(chars, 39, 49, "ON")
    _put(chars, 52, 56, "R$")
    _put(chars, 108, 121, f"{close_cents:013d}")
    _put(chars, 147, 152, "00123")
    _put(chars, 170, 188, f"{12345678:018d}")
    _put(chars, 210, 217, "0000001")
    _put(chars, 230, 242, "BRBMOBACNOR1")
    _put(chars, 242, 245, "100")
    return "".join(chars)


def _b3_zip(line: str) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("COTAHIST_A2025.TXT", "00HEADER\n" + line + "\n99TRAILER\n")
    return output.getvalue()


def _investing_sample() -> str:
    return (
        '"Date","Price","Open","High","Low","Vol.","Change %"\n'
        '"08/19/2024","8.30","8.30","8.30","8.30","1K","0%"\n'
        '"08/09/2022","8.82","8.08","9.10","7.29","1K","17.60%"\n'
        '"08/08/2022","7.50","7.82","7.89","7.50","1K","-1.21%"\n'
        '"07/29/2022","7.76","7.76","7.76","7.76","1K","0%"\n'
        '"12/30/2021","7.07","7.07","7.07","7.07","1K","0%"\n'
        '"06/30/2021","8.42","8.42","8.42","8.42","1K","0%"\n'
    )


def test_b3_fixed_width_parser_uses_official_price_positions() -> None:
    parsed = parse_cotahist_line(_b3_line(close_cents=3120))
    assert parsed is not None
    assert parsed.trading_date == "2025-12-30"
    assert parsed.ticker == "BMOB3"
    assert parsed.close == Decimal("31.20")
    assert parsed.quotation_factor == 1
    assert parsed.isin == "BRBMOBACNOR1"


def test_ecb_cross_rates_from_eur_reference_rates() -> None:
    text = (
        "KEY,FREQ,CURRENCY,CURRENCY_DENOM,EXR_TYPE,EXR_SUFFIX,TIME_PERIOD,OBS_VALUE\n"
        "x,D,BRL,EUR,SP00,A,2025-12-30,6.0\n"
        "x,D,NOK,EUR,SP00,A,2025-12-30,10.8\n"
        "x,D,USD,EUR,SP00,A,2025-12-30,1.08\n"
    )
    rows = derive_nok_cross_rates(parse_ecb_csv(text))
    values = {(row.base_currency, row.quote_currency): row.rate for row in rows}
    assert values[("BRL", "NOK")] == Decimal("1.8")
    assert values[("USD", "NOK")] == Decimal("10")


@pytest.mark.parametrize("invalid_value", ["0", "-1.2", "NaN", "Infinity", "ukjent"])
def test_ecb_parser_rejects_invalid_reference_rates(invalid_value: str) -> None:
    text = f"CURRENCY,TIME_PERIOD,OBS_VALUE\nNOK,2025-12-30,{invalid_value}\n"

    with pytest.raises(ValueError, match="Ugyldig ECB-kurs for NOK"):
        parse_ecb_csv(text)


def test_euronext_csv_parser_handles_semicolon_and_decimal_comma() -> None:
    text = "Date;Closing Price\n29/12/2025;16,90\n30/12/2025;17,20\n"
    prices = parse_euronext_historical_csv(text, date_order="DMY")
    assert [item.trading_date for item in prices] == ["2025-12-29", "2025-12-30"]
    assert prices[-1].close == Decimal("17.20")


@pytest.mark.parametrize("invalid_price", ["0", "-1.20", "NaN", "Infinity"])
def test_euronext_csv_parser_rejects_invalid_prices(invalid_price: str) -> None:
    text = f"Date;Closing Price\n30/12/2025;{invalid_price}\n"

    with pytest.raises(ValueError, match="Ugyldig Euronext-sluttkurs"):
        parse_euronext_historical_csv(text, date_order="DMY")


def test_investing_otec_reconstruction_reverses_2022_distribution() -> None:
    raw = parse_investing_historical_csv(_investing_sample())
    prices, adjustment = reconstruct_otec_2022_distribution(raw)
    by_date = {item.trading_date: item for item in prices}

    assert adjustment.last_including_date == "2022-08-08"
    assert adjustment.adjusted_close_last_including == Decimal("7.50")
    assert adjustment.reconstructed_close_last_including == Decimal("28.50")
    assert adjustment.reconstruction_multiplier == Decimal("3.8")

    assert by_date["2021-06-30"].close == Decimal("32.00")
    assert by_date["2021-06-30"].quality == "RECONSTRUCTED"
    assert by_date["2021-12-30"].close == Decimal("26.87")
    assert by_date["2022-07-29"].close == Decimal("29.49")
    assert by_date["2022-08-08"].close == Decimal("28.50")
    assert by_date["2022-08-09"].close == Decimal("8.82")
    assert by_date["2022-08-09"].quality == "DIRECT"


def test_investing_import_validates_euronext_overlap_and_counts_unique_dates(tmp_path) -> None:
    database_path = str(tmp_path / "investing.db")
    init_database(database_path)

    assert import_euronext_otec_csv(
        "Date,Closing Price\n19/08/2024,8.30\n",
        database_path=database_path,
    ) == 1

    result = import_investing_otec_csv(_investing_sample(), database_path=database_path)
    assert result["rows_written"] == 6
    assert result["reconstructed_rows"] == 4
    assert result["direct_rows"] == 2
    assert result["euronext_overlap_checked"] == 1
    assert result["reconstruction_multiplier"] == "3.8"

    status = market_data_status(database_path)
    assert status["OTEC"]["count"] == 6
    assert status["OTEC"]["rows_total"] == 7
    assert status["OTEC"]["reconstructed_dates"] == 4
    assert status["OTEC"]["direct_dates"] == 2

    with get_connection(database_path) as connection:
        row = connection.execute(
            """
            SELECT mp.price, mp.quality, mp.metadata_json
            FROM market_prices mp
            JOIN sources s ON s.id = mp.source_id
            WHERE s.code = 'INVESTING' AND mp.trading_date = '2021-06-30'
            """
        ).fetchone()
        assert row["price"] == "32.00"
        assert row["quality"] == "RECONSTRUCTED"
        assert '"source_close": "8.42"' in row["metadata_json"]


def test_market_data_import_and_core_nav_anchor(tmp_path) -> None:
    database_path = str(tmp_path / "market.db")
    init_database(database_path)
    seed_curated_history(database_path)

    assert import_b3_bmob3_zip(
        _b3_zip(_b3_line(close_cents=3000)), year=2025, database_path=database_path
    ) == 1

    ecb_text = (
        "KEY,FREQ,CURRENCY,CURRENCY_DENOM,EXR_TYPE,EXR_SUFFIX,TIME_PERIOD,OBS_VALUE\n"
        "x,D,BRL,EUR,SP00,A,2025-12-30,6.0\n"
        "x,D,NOK,EUR,SP00,A,2025-12-30,10.8\n"
        "x,D,USD,EUR,SP00,A,2025-12-30,1.08\n"
    )
    assert import_ecb_fx_csv(
        ecb_text,
        source_url="https://data-api.ecb.europa.eu/test",
        database_path=database_path,
    ) == 2

    assert import_euronext_otec_csv(
        "Date,Closing Price\n30/12/2025,17.20\n",
        database_path=database_path,
    ) == 1

    status = market_data_status(database_path)
    assert status["BMOB3"]["count"] == 1
    assert status["OTEC"]["count"] == 1
    assert status["BRL_NOK"]["count"] == 1
    assert status["USD_NOK"]["count"] == 1

    result = rebuild_core_nav_anchors(database_path)
    assert result["written"] == 1
    assert len(result["skipped"]) == 9

    with get_connection(database_path) as connection:
        snapshot = connection.execute(
            """
            SELECT nav_total_nok, nav_per_share_nok, otec_price_nok, discount_pct,
                   bemobi_value_nok, cash_estimate_nok, shares_outstanding,
                   nav_scope, status, components_json, quality_notes
            FROM nav_snapshots
            WHERE calculation_version = 'core-market-nav-v1'
            """
        ).fetchone()

    bemobi_value = Decimal("30") * Decimal(32_719_588) * Decimal("1.8")
    cash_value = Decimal(15_881_000) * Decimal("10")
    total = bemobi_value + cash_value
    per_share = total / Decimal(71_397_087)
    discount = (Decimal("1") - Decimal("17.20") / per_share) * Decimal("100")

    assert Decimal(snapshot["bemobi_value_nok"]) == bemobi_value
    assert Decimal(snapshot["cash_estimate_nok"]) == cash_value
    assert Decimal(snapshot["nav_total_nok"]) == total
    assert Decimal(snapshot["nav_per_share_nok"]) == per_share
    assert Decimal(snapshot["discount_pct"]) == discount
    assert snapshot["shares_outstanding"] == 71_397_087
    assert snapshot["nav_scope"] == "CORE"
    assert snapshot["status"] == "BACKFILLED"
    assert "other net assets" in snapshot["quality_notes"]

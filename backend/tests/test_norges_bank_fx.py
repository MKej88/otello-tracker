import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.marketdata.norges_bank_fx import (
    build_norges_bank_url,
    parse_norges_bank_sdmx_json,
)


def _sample_payload(unit_mult: str = "0") -> dict:
    return {
        "dataSets": [
            {
                "series": {
                    "0:0:0:0": {
                        "attributes": [0],
                        "observations": {"0": [6.71], "1": [6.76]},
                    },
                    "0:1:0:0": {
                        "attributes": [0],
                        "observations": {"0": [1.82], "1": [1.84]},
                    },
                    "0:2:0:0": {
                        "attributes": [0],
                        "observations": {"0": [10.25], "1": [10.31]},
                    },
                }
            }
        ],
        "structure": {
            "dimensions": {
                "series": [
                    {"id": "FREQ", "values": [{"id": "B"}]},
                    {
                        "id": "BASE_CUR",
                        "values": [{"id": "AUD"}, {"id": "BRL"}, {"id": "USD"}],
                    },
                    {"id": "QUOTE_CUR", "values": [{"id": "NOK"}]},
                    {"id": "TENOR", "values": [{"id": "SP"}]},
                ],
                "observation": [
                    {
                        "id": "TIME_PERIOD",
                        "values": [{"id": "2026-08-18"}, {"id": "2026-08-19"}],
                    }
                ],
            },
            "attributes": {
                "series": [{"id": "UNIT_MULT", "values": [{"id": unit_mult}]}]
            },
        },
    }


def test_norges_bank_parser_reads_direct_aud_brl_and_usd_nok() -> None:
    rows = parse_norges_bank_sdmx_json(json.dumps(_sample_payload()))
    values = {(row.trading_date, row.base_currency): row.rate for row in rows}

    assert values[("2026-08-18", "AUD")] == Decimal("6.71")
    assert values[("2026-08-19", "AUD")] == Decimal("6.76")
    assert values[("2026-08-18", "BRL")] == Decimal("1.82")
    assert values[("2026-08-19", "BRL")] == Decimal("1.84")
    assert values[("2026-08-18", "USD")] == Decimal("10.25")
    assert values[("2026-08-19", "USD")] == Decimal("10.31")
    assert all(row.quote_currency == "NOK" for row in rows)


def test_norges_bank_parser_uses_dimension_order_from_payload() -> None:
    payload = _sample_payload()
    dimensions = payload["structure"]["dimensions"]["series"]
    dimensions[:] = [dimensions[1], dimensions[3], dimensions[0], dimensions[2]]
    series = payload["dataSets"][0]["series"]
    series["1:0:0:0"] = series.pop("0:1:0:0")
    series["2:0:0:0"] = series.pop("0:2:0:0")

    rows = parse_norges_bank_sdmx_json(payload)

    assert {row.base_currency for row in rows} == {"AUD", "BRL", "USD"}


def test_norges_bank_parser_fails_closed_on_unit_multiplier() -> None:
    with pytest.raises(ValueError, match="UNIT_MULT"):
        parse_norges_bank_sdmx_json(_sample_payload("2"))


def test_norges_bank_parser_rejects_invalid_trading_date() -> None:
    payload = _sample_payload()
    time_values = payload["structure"]["dimensions"]["observation"][0]["values"]
    time_values[0]["id"] = "2026-02-30"

    with pytest.raises(ValueError, match="Ugyldig observasjon"):
        parse_norges_bank_sdmx_json(payload)


def test_norges_bank_parser_rejects_date_missing_one_currency() -> None:
    payload = _sample_payload()
    del payload["dataSets"][0]["series"]["0:2:0:0"]["observations"]["1"]

    with pytest.raises(
        ValueError,
        match=r"ufullstendige valutadatoer: 2026-08-19 mangler USD",
    ):
        parse_norges_bank_sdmx_json(payload)


def test_norges_bank_parser_reports_every_missing_currency_by_date() -> None:
    payload = _sample_payload()
    series = payload["dataSets"][0]["series"]
    del series["0:0:0:0"]["observations"]["0"]
    del series["0:1:0:0"]["observations"]["1"]
    del series["0:2:0:0"]["observations"]["1"]

    with pytest.raises(
        ValueError,
        match=(
            r"ufullstendige valutadatoer: 2026-08-18 mangler AUD; "
            r"2026-08-19 mangler BRL, USD"
        ),
    ):
        parse_norges_bank_sdmx_json(payload)


@pytest.mark.parametrize("invalid_rate", ["NaN", "Infinity", "-Infinity"])
def test_norges_bank_parser_rejects_non_finite_rates(invalid_rate: str) -> None:
    payload = _sample_payload()
    payload["dataSets"][0]["series"]["0:1:0:0"]["observations"]["0"] = [invalid_rate]

    with pytest.raises(ValueError, match="Ugyldig BRL/NOK-kurs"):
        parse_norges_bank_sdmx_json(payload)


def test_norges_bank_url_requests_direct_nok_pairs() -> None:
    url = build_norges_bank_url("2026-08-01", "2026-08-20")
    assert "/EXR/B.AUD+BRL+USD.NOK.SP?" in url
    assert "format=sdmx-json" in url
    assert "startPeriod=2026-08-01" in url
    assert "endPeriod=2026-08-20" in url


def test_norges_bank_source_migrations_match() -> None:
    root = Path(__file__).resolve().parents[2]
    sqlite = (
        root / "backend/app/db/migrations/0021_norges_bank_fx_source.sql"
    ).read_text()
    d1 = (root / "cloudflare/migrations/0011_norges_bank_fx_source.sql").read_text()
    assert sqlite == d1
    assert "NORGES_BANK" in sqlite
    assert "data.norges-bank.no" in sqlite

import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.marketdata.norges_bank_fx import build_norges_bank_url, parse_norges_bank_sdmx_json


def _sample_payload(unit_mult: str = "0") -> dict:
    return {
        "dataSets": [
            {
                "series": {
                    "0:0:0:0": {
                        "attributes": [0],
                        "observations": {"0": [1.82], "1": [1.84]},
                    },
                    "0:1:0:0": {
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
                    {"id": "BASE_CUR", "values": [{"id": "BRL"}, {"id": "USD"}]},
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
                "series": [
                    {"id": "UNIT_MULT", "values": [{"id": unit_mult}]}
                ]
            },
        },
    }


def test_norges_bank_parser_reads_direct_brl_and_usd_nok() -> None:
    rows = parse_norges_bank_sdmx_json(json.dumps(_sample_payload()))
    values = {(row.trading_date, row.base_currency): row.rate for row in rows}

    assert values[("2026-08-18", "BRL")] == Decimal("1.82")
    assert values[("2026-08-19", "BRL")] == Decimal("1.84")
    assert values[("2026-08-18", "USD")] == Decimal("10.25")
    assert values[("2026-08-19", "USD")] == Decimal("10.31")
    assert all(row.quote_currency == "NOK" for row in rows)


def test_norges_bank_parser_fails_closed_on_unit_multiplier() -> None:
    with pytest.raises(ValueError, match="UNIT_MULT"):
        parse_norges_bank_sdmx_json(_sample_payload("2"))


@pytest.mark.parametrize("invalid_rate", ["NaN", "Infinity", "-Infinity"])
def test_norges_bank_parser_rejects_non_finite_rates(invalid_rate: str) -> None:
    payload = _sample_payload()
    payload["dataSets"][0]["series"]["0:0:0:0"]["observations"]["0"] = [
        invalid_rate
    ]

    with pytest.raises(ValueError, match="Ugyldig BRL/NOK-kurs"):
        parse_norges_bank_sdmx_json(payload)


def test_norges_bank_url_requests_direct_nok_pairs() -> None:
    url = build_norges_bank_url("2026-08-01", "2026-08-20")
    assert "/EXR/B.BRL+USD.NOK.SP?" in url
    assert "format=sdmx-json" in url
    assert "startPeriod=2026-08-01" in url
    assert "endPeriod=2026-08-20" in url


def test_norges_bank_source_migrations_match() -> None:
    root = Path(__file__).resolve().parents[2]
    sqlite = (root / "backend/app/db/migrations/0021_norges_bank_fx_source.sql").read_text()
    d1 = (root / "cloudflare/migrations/0011_norges_bank_fx_source.sql").read_text()
    assert sqlite == d1
    assert "NORGES_BANK" in sqlite
    assert "data.norges-bank.no" in sqlite

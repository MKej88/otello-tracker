from __future__ import annotations

import sys
from pathlib import Path

import pytest

CLOUDFLARE_SRC = Path(__file__).resolve().parents[2] / "cloudflare" / "src"
if str(CLOUDFLARE_SRC) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE_SRC))

from norges_bank_full_refresh import parse_norges_bank_sdmx_json  # noqa: E402


def test_parser_rejects_partial_trading_date() -> None:
    payload = {
        "dataSets": [
            {
                "series": {
                    "0:0:0:0": {"observations": {"0": [6.71], "1": [6.76]}},
                    "0:1:0:0": {"observations": {"0": [1.82], "1": [1.84]}},
                    "0:2:0:0": {"observations": {"0": [10.25]}},
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
            }
        },
    }

    with pytest.raises(
        ValueError,
        match=r"ufullstendige valutadatoer: 2026-08-19 mangler USD",
    ):
        parse_norges_bank_sdmx_json(payload)

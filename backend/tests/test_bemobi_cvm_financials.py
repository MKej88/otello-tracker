from __future__ import annotations

import csv
import io
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
if str(CLOUDFLARE_SRC) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE_SRC))

from bemobi_cvm_financials import (  # noqa: E402
    BEMOBI_CVM_CODE,
    derive_reported_quarters,
    parse_parent_net_income_archive,
)


FIELDS = [
    "CNPJ_CIA",
    "DT_REFER",
    "VERSAO",
    "DENOM_CIA",
    "CD_CVM",
    "GRUPO_DFP",
    "MOEDA",
    "ESCALA_MOEDA",
    "ORDEM_EXERC",
    "DT_INI_EXERC",
    "DT_FIM_EXERC",
    "CD_CONTA",
    "DS_CONTA",
    "VL_CONTA",
    "ST_CONTA_FIXA",
]


def _row(*, year: int, period_end: str, value: str, version: int = 1, **overrides):
    row = {
        "CNPJ_CIA": "09.042.817/0001-05",
        "DT_REFER": period_end,
        "VERSAO": str(version),
        "DENOM_CIA": "BEMOBI MOBILE TECH S.A.",
        "CD_CVM": BEMOBI_CVM_CODE,
        "GRUPO_DFP": "DF Consolidado - Demonstração do Resultado",
        "MOEDA": "REAL",
        "ESCALA_MOEDA": "MIL",
        "ORDEM_EXERC": "ÚLTIMO",
        "DT_INI_EXERC": f"{year}-01-01",
        "DT_FIM_EXERC": period_end,
        "CD_CONTA": "3.11.01",
        "DS_CONTA": "Atribuído a Sócios da Empresa Controladora",
        "VL_CONTA": value,
        "ST_CONTA_FIXA": "S",
    }
    row.update(overrides)
    return row


def _archive(*, year: int, document_type: str, rows: list[dict]) -> bytes:
    text = io.StringIO()
    writer = csv.DictWriter(text, fieldnames=FIELDS, delimiter=";", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            f"{document_type}_cia_aberta_DRE_con_{year}.csv",
            text.getvalue().encode("cp1252"),
        )
    return buffer.getvalue()


def test_parser_filters_bemobi_parent_income_and_keeps_latest_version() -> None:
    payload = _archive(
        year=2026,
        document_type="itr",
        rows=[
            _row(year=2026, period_end="2026-03-31", value="34210"),
            _row(year=2026, period_end="2026-06-30", value="65000", version=1),
            _row(year=2026, period_end="2026-06-30", value="67445", version=2),
            _row(
                year=2026,
                period_end="2026-06-30",
                value="999999",
                version=2,
                CD_CVM="99999",
            ),
            _row(
                year=2026,
                period_end="2026-06-30",
                value="888888",
                version=2,
                CD_CONTA="3.11.02",
            ),
            _row(
                year=2026,
                period_end="2026-06-30",
                value="777777",
                version=2,
                ORDEM_EXERC="PENÚLTIMO",
            ),
        ],
    )

    rows = parse_parent_net_income_archive(payload, year=2026, document_type="itr")
    assert [(row.period_end, row.version, row.value_mbrl) for row in rows] == [
        ("2026-03-31", 1, 34.21),
        ("2026-06-30", 2, 67.445),
    ]


def test_quarter_derivation_reproduces_bemobi_2q26_ttm_building_blocks() -> None:
    itr_2026 = parse_parent_net_income_archive(
        _archive(
            year=2026,
            document_type="itr",
            rows=[
                _row(year=2026, period_end="2026-03-31", value="34210"),
                _row(year=2026, period_end="2026-06-30", value="67445"),
            ],
        ),
        year=2026,
        document_type="itr",
    )
    quarters_2026 = derive_reported_quarters(year=2026, itr_observations=itr_2026)
    assert quarters_2026["1Q26"]["reported_net_income_parent_mbrl"] == 34.21
    assert quarters_2026["2Q26"]["reported_net_income_parent_mbrl"] == 33.235
    assert quarters_2026["2Q26"]["reported_net_income_parent_account"] == "3.11.01"

    itr_2025 = parse_parent_net_income_archive(
        _archive(
            year=2025,
            document_type="itr",
            rows=[
                _row(year=2025, period_end="2025-06-30", value="64405"),
                _row(year=2025, period_end="2025-09-30", value="105424"),
            ],
        ),
        year=2025,
        document_type="itr",
    )
    dfp_2025 = parse_parent_net_income_archive(
        _archive(
            year=2025,
            document_type="dfp",
            rows=[_row(year=2025, period_end="2025-12-31", value="156660")],
        ),
        year=2025,
        document_type="dfp",
    )
    quarters_2025 = derive_reported_quarters(
        year=2025,
        itr_observations=itr_2025,
        dfp_observations=dfp_2025,
    )
    assert quarters_2025["3Q25"]["reported_net_income_parent_mbrl"] == 41.019
    assert quarters_2025["4Q25"]["reported_net_income_parent_mbrl"] == 51.236

    ttm = sum(
        [
            quarters_2025["3Q25"]["reported_net_income_parent_mbrl"],
            quarters_2025["4Q25"]["reported_net_income_parent_mbrl"],
            quarters_2026["1Q26"]["reported_net_income_parent_mbrl"],
            quarters_2026["2Q26"]["reported_net_income_parent_mbrl"],
        ]
    )
    assert abs(ttm - 159.7) < 1e-12


def test_scale_conversion_supports_cvm_unit_scale() -> None:
    rows = parse_parent_net_income_archive(
        _archive(
            year=2026,
            document_type="itr",
            rows=[
                _row(
                    year=2026,
                    period_end="2026-03-31",
                    value="34210000",
                    ESCALA_MOEDA="UNIDADE",
                )
            ],
        ),
        year=2026,
        document_type="itr",
    )
    assert rows[0].value_mbrl == 34.21

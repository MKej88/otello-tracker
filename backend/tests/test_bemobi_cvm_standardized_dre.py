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
    derive_standardized_dre_quarters,
    parse_dre_accounts_archive,
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


def _row(*, year: int, period_end: str, account: str, value: str, version: int = 1):
    labels = {
        "3.01": "Receita de Venda de Bens e/ou Serviços",
        "3.05": "Resultado Antes do Resultado Financeiro e dos Tributos",
        "3.11.01": "Atribuído a Sócios da Empresa Controladora",
    }
    return {
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
        "CD_CONTA": account,
        "DS_CONTA": labels[account],
        "VL_CONTA": value,
        "ST_CONTA_FIXA": "S",
    }


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


def test_standardized_cvm_dre_derives_revenue_ebit_and_parent_income() -> None:
    rows = []
    for account, q1, h1 in (
        ("3.01", "120000", "255000"),
        ("3.05", "30000", "65000"),
        ("3.11.01", "34210", "67445"),
    ):
        rows.extend(
            [
                _row(year=2026, period_end="2026-03-31", account=account, value=q1),
                _row(year=2026, period_end="2026-06-30", account=account, value=h1),
            ]
        )

    observations = parse_dre_accounts_archive(
        _archive(year=2026, document_type="itr", rows=rows),
        year=2026,
        document_type="itr",
    )
    quarters = derive_standardized_dre_quarters(
        year=2026,
        itr_observations=observations,
    )

    assert quarters["1Q26"]["reported_revenue_mbrl"] == 120.0
    assert quarters["2Q26"]["reported_revenue_mbrl"] == 135.0
    assert quarters["2Q26"]["reported_ebit_mbrl"] == 35.0
    assert quarters["2Q26"]["reported_net_income_parent_mbrl"] == 33.235
    assert quarters["2Q26"]["reported_revenue_account"] == "3.01"
    assert quarters["2Q26"]["reported_ebit_account"] == "3.05"
    assert quarters["2Q26"]["reported_net_income_parent_account"] == "3.11.01"


def test_standardized_cvm_dre_uses_dfp_to_derive_q4() -> None:
    itr_rows = []
    dfp_rows = []
    for account, h1, nine_month, full_year in (
        ("3.01", "250000", "390000", "540000"),
        ("3.05", "60000", "95000", "135000"),
        ("3.11.01", "64405", "105424", "156660"),
    ):
        itr_rows.extend(
            [
                _row(year=2025, period_end="2025-06-30", account=account, value=h1),
                _row(year=2025, period_end="2025-09-30", account=account, value=nine_month),
            ]
        )
        dfp_rows.append(
            _row(year=2025, period_end="2025-12-31", account=account, value=full_year)
        )

    itr = parse_dre_accounts_archive(
        _archive(year=2025, document_type="itr", rows=itr_rows),
        year=2025,
        document_type="itr",
    )
    dfp = parse_dre_accounts_archive(
        _archive(year=2025, document_type="dfp", rows=dfp_rows),
        year=2025,
        document_type="dfp",
    )
    quarters = derive_standardized_dre_quarters(
        year=2025,
        itr_observations=itr,
        dfp_observations=dfp,
    )

    assert quarters["3Q25"]["reported_revenue_mbrl"] == 140.0
    assert quarters["4Q25"]["reported_revenue_mbrl"] == 150.0
    assert quarters["4Q25"]["reported_ebit_mbrl"] == 40.0
    assert quarters["4Q25"]["reported_net_income_parent_mbrl"] == 51.236

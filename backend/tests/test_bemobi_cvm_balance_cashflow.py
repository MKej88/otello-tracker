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
    derive_standardized_balance_quarters,
    derive_standardized_cashflow_quarters,
    parse_statement_accounts_archive,
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


def _row(*, year: int, period_end: str, account: str, value: str, statement: str):
    labels = {
        "6.01": "Caixa Líquido Atividades Operacionais",
        "6.02.02": "Investimentos / Capex",
        "1.01.01": "Caixa e Equivalentes de Caixa",
        "2.01.04": "Empréstimos e Financiamentos",
        "2.02.01": "Empréstimos e Financiamentos",
    }
    return {
        "CNPJ_CIA": "09.042.817/0001-05",
        "DT_REFER": period_end,
        "VERSAO": "1",
        "DENOM_CIA": "BEMOBI MOBILE TECH S.A.",
        "CD_CVM": BEMOBI_CVM_CODE,
        "GRUPO_DFP": f"DF Consolidado - {statement}",
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


def _archive(*, year: int, document_type: str, files: dict[str, list[dict]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for statement, rows in files.items():
            text = io.StringIO()
            writer = csv.DictWriter(text, fieldnames=FIELDS, delimiter=";", lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
            suffix = "DFC_MI" if statement == "DFC" else statement
            archive.writestr(
                f"{document_type}_cia_aberta_{suffix}_con_{year}.csv",
                text.getvalue().encode("cp1252"),
            )
    return buffer.getvalue()


def test_cvm_cashflow_derives_standalone_quarter_and_capex() -> None:
    payload = _archive(
        year=2026,
        document_type="itr",
        files={
            "DFC": [
                _row(year=2026, period_end="2026-03-31", account="6.01", value="20000", statement="DFC"),
                _row(year=2026, period_end="2026-06-30", account="6.01", value="47000", statement="DFC"),
                _row(year=2026, period_end="2026-03-31", account="6.02.02", value="-3000", statement="DFC"),
                _row(year=2026, period_end="2026-06-30", account="6.02.02", value="-8000", statement="DFC"),
            ]
        },
    )
    rows = parse_statement_accounts_archive(
        payload,
        year=2026,
        document_type="itr",
        statement="DFC",
        account_codes={"6.01", "6.02.02"},
    )
    quarters = derive_standardized_cashflow_quarters(year=2026, itr_observations=rows)
    assert quarters["1Q26"]["reported_operating_cash_flow_mbrl"] == 20.0
    assert quarters["2Q26"]["reported_operating_cash_flow_mbrl"] == 27.0
    assert quarters["2Q26"]["reported_operating_cash_flow_account"] == "6.01"
    assert quarters["1Q26"]["reported_capex_cash_outflow_mbrl"] == -3.0
    assert quarters["2Q26"]["reported_capex_cash_outflow_mbrl"] == -5.0
    assert quarters["2Q26"]["reported_capex_cash_outflow_account"] == "6.02.02"


def test_cvm_balance_builds_cash_borrowings_and_net_debt() -> None:
    payload = _archive(
        year=2026,
        document_type="itr",
        files={
            "BPA": [
                _row(year=2026, period_end="2026-06-30", account="1.01.01", value="180000", statement="BPA"),
            ],
            "BPP": [
                _row(year=2026, period_end="2026-06-30", account="2.01.04", value="25000", statement="BPP"),
                _row(year=2026, period_end="2026-06-30", account="2.02.01", value="40000", statement="BPP"),
            ],
        },
    )
    bpa = parse_statement_accounts_archive(
        payload,
        year=2026,
        document_type="itr",
        statement="BPA",
        account_codes={"1.01.01"},
    )
    bpp = parse_statement_accounts_archive(
        payload,
        year=2026,
        document_type="itr",
        statement="BPP",
        account_codes={"2.01.04", "2.02.01"},
    )
    quarters = derive_standardized_balance_quarters(
        year=2026,
        itr_bpa=bpa,
        itr_bpp=bpp,
    )
    q2 = quarters["2Q26"]
    assert q2["reported_cash_mbrl"] == 180.0
    assert q2["reported_borrowings_current_mbrl"] == 25.0
    assert q2["reported_borrowings_noncurrent_mbrl"] == 40.0
    assert q2["reported_borrowings_mbrl"] == 65.0
    assert q2["reported_net_debt_mbrl"] == -115.0
    assert q2["reported_net_debt_method"] == "CVM_BORROWINGS_MINUS_CASH"

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

from bemobi_cvm_financials import BEMOBI_CVM_CODE, parse_statement_accounts_archive  # noqa: E402

FIELDS = [
    "CNPJ_CIA", "DT_REFER", "VERSAO", "DENOM_CIA", "CD_CVM", "GRUPO_DFP",
    "MOEDA", "ESCALA_MOEDA", "ORDEM_EXERC", "DT_INI_EXERC", "DT_FIM_EXERC",
    "CD_CONTA", "DS_CONTA", "VL_CONTA", "ST_CONTA_FIXA",
]


def _csv(value: str, *, cvm_code: str = BEMOBI_CVM_CODE) -> bytes:
    text = io.StringIO()
    writer = csv.DictWriter(text, fieldnames=FIELDS, delimiter=";", lineterminator="\n")
    writer.writeheader()
    writer.writerow({
        "CNPJ_CIA": "09.042.817/0001-05",
        "DT_REFER": "2026-06-30",
        "VERSAO": "1",
        "DENOM_CIA": "BEMOBI MOBILE TECH S.A.",
        "CD_CVM": cvm_code,
        "GRUPO_DFP": "DF Consolidado - Demonstração do Fluxo de Caixa",
        "MOEDA": "REAL",
        "ESCALA_MOEDA": "MIL",
        "ORDEM_EXERC": "ÚLTIMO",
        "DT_INI_EXERC": "2026-01-01",
        "DT_FIM_EXERC": "2026-06-30",
        "CD_CONTA": "6.01",
        "DS_CONTA": "Caixa Líquido Atividades Operacionais",
        "VL_CONTA": value,
        "ST_CONTA_FIXA": "S",
    })
    return text.getvalue().encode("cp1252")


def test_bemobi_prefers_indirect_dfc_when_archive_contains_both_methods() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("itr_cia_aberta_DFC_MI_con_2026.csv", _csv("47000"))
        archive.writestr("itr_cia_aberta_DFC_MD_con_2026.csv", _csv("999000", cvm_code="99999"))

    rows = parse_statement_accounts_archive(
        buffer.getvalue(),
        year=2026,
        document_type="itr",
        statement="DFC",
        account_codes={"6.01"},
    )
    assert len(rows) == 1
    assert rows[0].value_mbrl == 47.0

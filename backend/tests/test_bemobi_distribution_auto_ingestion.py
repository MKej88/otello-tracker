"""Verified Bemobi notice -> corporate action -> receivable/cash ingestion."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "cloudflare" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import bemobi_distribution_ingestion as ingestion  # noqa: E402
from bemobi_ir_news import COMPANY_ID  # noqa: E402


Q3_URL = f"https://filemanager-cdn.mziq.com/published/{COMPANY_ID}/q3-2026-jcp"
Q2_URL = f"https://filemanager-cdn.mziq.com/published/{COMPANY_ID}/q2-2026-jcp"

# Same formatting and core clauses as Bemobi's official 1Q26 shareholder
# notice; the Q3 amounts and dates match its publicly announced 3Q26 JCP.
Q3_NOTICE = """
BEMOBI MOBILE TECH S.A.
CNPJ/MF nº 09.042.817/0001-05
Companhia Aberta
Ticker: BMOB3
AVISO AOS ACIONISTAS
Juros Sobre Capital Próprio
Bemobi Mobile Tech S.A. (BMOB3) comunica aos seus acionistas que
deliberou sobre a distribuição e pagamento de juros sobre capital próprio
("JCP 3T26") nos seguintes termos:
(a) O valor total da distribuição será de R$ 16.000.000,00
(dezesseis milhões de reais), correspondente ao
valor bruto de R$ 0,19178292 por ação, e ao valor líquido de
R$ 13.200.000,00 (treze milhões e duzentos mil reais),
correspondente a R$ 0,15822091 por ação.
(b) Farão jus ao recebimento os acionistas da Companhia no fechamento
do pregão de 17 de novembro de 2026.
(c) As ações serão negociadas na condição “ex-juros sobre o capital próprio”
a partir de 18 de novembro de 2026 (inclusive).
(e) O pagamento de juros sobre o capital próprio aos acionistas ocorrerá
em 30 de novembro de 2026.
(f) O valor total dos juros sobre o capital próprio estará sujeito à retenção
do imposto de renda na fonte à alíquota de 17,5%, exceto para acionistas isentos.
Rio de Janeiro, 12 de novembro de 2026
"""

Q2_NOTICE = (
    Q3_NOTICE
    .replace("3T26", "2T26")
    .replace("17 de novembro", "14 de agosto")
    .replace("18 de novembro", "17 de agosto")
    .replace("30 de novembro", "28 de agosto")
    .replace("12 de novembro", "11 de agosto")
)


class MemoryRepository:
    def __init__(self, notices):
        self.rows = notices
        self.actions = []
        self.documents = []
        self.writes = 0

    async def first(self, sql, parameters=()):
        if "FROM runtime_state" in sql:
            return {"value": json.dumps({
                "checked_date": "2026-11-18", "rows": self.rows,
            })}
        if "FROM corporate_actions" in sql:
            external_id, action_type, ex_date, payment_date = parameters
            return next((
                row for row in self.actions
                if row["external_action_id"] == external_id
                or (row["action_type"] == action_type and row["ex_date"] == ex_date
                    and row["payment_date"] == payment_date)
            ), None)
        raise AssertionError(sql)

    async def create_source_document(self, **kwargs):
        self.documents.append(kwargs)
        return len(self.documents)

    async def instrument_id(self, symbol):
        assert symbol == "BMOB3"
        return 101

    async def run(self, sql, parameters=()):
        assert "INSERT INTO corporate_actions" in sql
        assert "ON CONFLICT DO NOTHING" in sql
        self.writes += 1
        self.actions.append({
            "external_action_id": parameters[10],
            "action_type": parameters[1],
            "ex_date": parameters[3],
            "payment_date": parameters[5],
            "amount_per_share": parameters[6],
            "withholding_rate": parameters[15],
        })


def notice(identifier, url, day, title="Dividendos/Juros sobre Capital Próprio"):
    return {
        "document_kind": "NOTICE",
        "category": "aviso-acionistas",
        "id": identifier,
        "date": day,
        "title": title,
        "original_title": title,
        "url": url,
    }


def test_real_q2_pdf_number_spacing_and_ex_hyphen_are_parsed():
    # Representative fragments from Bemobi's actual 11 Aug 2026 PDF:
    # https://api.mziq.com/mzfilemanager/v2/d/deed72f2-beae-4c6f-b423-db57178bae31/4761cf80-96fc-b59c-9720-17addd9e1dc9?origin=2
    text = Q2_NOTICE.replace(
        "R$ 13.200.000,00", "R$ 13. 200.000,00"
    ).replace(
        "R$ 0,15822091", "R$ 0, 15822091"
    ).replace("ex-juros", "ex -juros")
    result = ingestion.parse_official_distribution(
        text, published_date="2026-08-11",
    )
    assert result["ex_date"] == "2026-08-17"
    assert result["payment_date"] == "2026-08-28"
    assert result["net_total_amount"] == "13200000.00"
    assert result["net_amount_per_share"] == "0.15822091"


def test_q3_notice_has_source_validated_entitlement_and_net_amount():
    result = ingestion.parse_official_distribution(
        Q3_NOTICE, published_date="2026-11-12",
    )
    assert result["action_type"] == "JCP"
    assert result["record_date"] == "2026-11-17"
    assert result["ex_date"] == "2026-11-18"
    assert result["payment_date"] == "2026-11-30"
    assert result["gross_total_amount"] == "16000000.00"
    assert result["gross_amount_per_share"] == "0.19178292"
    assert result["net_amount_per_share"] == "0.15822091"
    assert result["withholding_rate"] == "0.175"
    assert result["tax_treatment"] == "PUBLISHED_NET"


@pytest.mark.parametrize("replacement,reason", [
    (("BMOB3", "ANOTHER"), "issuer_not_verified"),
    (("0,15822091", "0,18822091"), "net_per_share_mismatch"),
    (("30 de novembro", "10 de novembro"), "inconsistent_distribution_dates"),
    (("17,5%", "15,0%"), "net_total_mismatch"),
    (("18 de novembro", "tbd"), "missing_ex_date"),
])
def test_unsafe_notice_never_produces_an_action(replacement, reason):
    text = Q3_NOTICE.replace(*replacement)
    with pytest.raises(ValueError, match=reason):
        ingestion.parse_official_distribution(text, published_date="2026-11-12")


def test_generic_notice_without_verified_distribution_is_ignored():
    text = Q3_NOTICE.replace("Juros Sobre Capital Próprio",
                             "Assunto de Governança").replace("juros sobre capital próprio",
                                                              "outra matéria")
    with pytest.raises(ValueError, match="not_distribution"):
        ingestion.parse_official_distribution(text, published_date="2026-11-12")


def test_new_official_q3_is_booked_once_and_old_q2_not_double_booked(monkeypatch):
    repo = MemoryRepository([
        notice("q3-jcp", Q3_URL, "2026-11-12"),
        notice("q2-jcp", Q2_URL, "2026-08-11"),
    ])
    repo.actions.append({
        "external_action_id": "bemobi-2026-08-28-jcp-2q26",
        "action_type": "JCP",
        "ex_date": "2026-08-17",
        "payment_date": "2026-08-28",
        "amount_per_share": "0.19178292",
    })

    async def fake_pdf(url, **kwargs):
        assert url in {Q3_URL, Q2_URL}
        return (b"%PDF-1.4-Q3" if url == Q3_URL else b"%PDF-1.4-Q2"), url, False

    monkeypatch.setattr(ingestion, "_fetch_result_payload", fake_pdf)
    monkeypatch.setattr(
        ingestion, "_pdf_text",
        lambda raw: Q3_NOTICE if b"Q3" in raw else Q2_NOTICE,
    )

    first = asyncio.run(ingestion.refresh_official_distributions(
        repo, target_date="2026-11-18",
    ))
    second = asyncio.run(ingestion.refresh_official_distributions(
        repo, target_date="2026-11-18",
    ))
    assert first["status"] == second["status"] == "ok"
    assert first["rows_written"] == 1
    assert first["unchanged"] == 1
    assert second["rows_written"] == 0
    assert second["unchanged"] == 2
    assert repo.writes == 1
    assert len(repo.documents) == 1
    assert repo.documents[0]["source_code"] == "BEMOBI_IR"
    assert repo.documents[0]["metadata"]["validation"] == "OFFICIAL_NOTICE_STRICT"
    assert len(repo.actions) == 2
    assert repo.actions[1]["ex_date"] == "2026-11-18"


def test_conflicting_existing_payment_is_flagged_not_booked(monkeypatch):
    repo = MemoryRepository([notice("q3-jcp", Q3_URL, "2026-11-12")])
    repo.actions.append({
        "external_action_id": "old-data",
        "action_type": "JCP", "ex_date": "2026-11-18",
        "payment_date": "2026-11-30", "amount_per_share": "0.10",
    })

    async def fake_pdf(url, **kwargs):
        return b"%PDF-1.4-Q3", url, False

    monkeypatch.setattr(ingestion, "_fetch_result_payload", fake_pdf)
    monkeypatch.setattr(ingestion, "_pdf_text", lambda _: Q3_NOTICE)

    result = asyncio.run(ingestion.refresh_official_distributions(
        repo, target_date="2026-11-18",
    ))
    assert result["status"] == "partial"
    assert result["review_required"] == 1
    assert result["review"][0]["reason"] == "conflicting_existing_distribution"
    assert repo.writes == 0
    assert repo.documents == []


def test_wrong_issuer_url_is_not_requested(monkeypatch):
    repo = MemoryRepository([notice(
        "q3-jcp", "https://other.example.com/notice", "2026-11-12",
    )])
    async def should_not_fetch(*args, **kwargs):
        raise AssertionError("Unknown host must never be fetched")

    monkeypatch.setattr(ingestion, "_fetch_result_payload", should_not_fetch)
    result = asyncio.run(ingestion.refresh_official_distributions(
        repo, target_date="2026-11-18",
    ))
    assert result["status"] == "ok"
    assert result["notices_checked"] == 0
    assert repo.writes == 0

# Representative English clauses and broken extraction from the actual
# 12 Nov 2026 official MZiQ Q3 shareholder notice. No guessed dates/amounts.
ENGLISH_Q3_NOTICE = """
BEMOBI MOBILE TECH S.A.
Corporate Taxpayer ID (CNPJ/MF) No. 09.042.817/0001-05
Publicly-Held Company
Ticker: BMOB3
NOTICE TO SHAREHOLDERS
Interest on Equity
Bemobi Mobile Tech S.A. hereby informs its shareholders that it resolved
on the distribution and payment of interest on equity ("IoE 3Q26"):
(a) The total distribution amount will be R$ 16,000,000.00,
corresponding to a gross value of R$ 0.19178292 per share,
and to a net value of R$ 13,200,000.00, corresponding to
R$ 0.15822 091 per share.
(b) Entitled to receive the interest on equity will be the Company's
shareholders at the close of the trading session on November 17 , 2026.
(c) The shares will be traded ex - interest on equity as from
November 18 , 2026 (inclusive).
(e) The payment of interest on equity to shareholders will take place
on November 30 , 2026.
(f) The total amount of interest on equity will be subject to withholding
income tax at the rate of 17.5 %, except for shareholders who are exempt.
"""


def test_q3_official_english_notice_is_validated_not_silently_ignored():
    parsed = ingestion.parse_official_distribution(
        ENGLISH_Q3_NOTICE, published_date="2026-11-12",
    )
    assert parsed["action_type"] == "JCP"
    assert parsed["record_date"] == "2026-11-17"
    assert parsed["ex_date"] == "2026-11-18"
    assert parsed["payment_date"] == "2026-11-30"
    assert parsed["gross_total_amount"] == "16000000.00"
    assert parsed["gross_amount_per_share"] == "0.19178292"
    assert parsed["net_total_amount"] == "13200000.00"
    assert parsed["net_amount_per_share"] == "0.15822091"
    assert parsed["withholding_rate"] == "0.175"


def test_q3_portuguese_cvm_pdf_split_groups_and_tax_are_not_lost():
    notice_text = (
        Q3_NOTICE.replace("13.200.000,00", "13. 2 00.000,00")
        .replace("0,15822091", "0, 158 22091")
        .replace("17,5%", "1 7, 5%")
    )
    parsed = ingestion.parse_official_distribution(
        notice_text, published_date="2026-11-12",
    )
    assert parsed["net_total_amount"] == "13200000.00"
    assert parsed["net_amount_per_share"] == "0.15822091"
    assert parsed["withholding_rate"] == "0.175"


@pytest.mark.parametrize("replacement,reason", [
    (("BMOB3", "OTHER"), "issuer_not_verified"),
    (("0.15822 091", "0.18822 091"), "net_per_share_mismatch"),
    (("November 18 , 2026", "November 10 , 2026"), "inconsistent_distribution_dates"),
    (("17.5 %", "15.0 %"), "net_total_mismatch"),
    (("November 30 , 2026", "date pending"), "missing_payment_date"),
])
def test_english_notice_rejects_unsafe_or_incomplete_data(replacement, reason):
    with pytest.raises(ValueError, match=reason):
        ingestion.parse_official_distribution(
            ENGLISH_Q3_NOTICE.replace(*replacement),
            published_date="2026-11-12",
        )


def test_live_style_english_q3_feed_ingests_once(monkeypatch):
    repo = MemoryRepository([
        notice(
            "official-q3-ioe",
            Q3_URL,
            "2026-11-12",
            title="Notice to Shareholders - Interest on Equity",
        )
    ])

    async def official_pdf(url, *, fetcher=None):
        assert url == Q3_URL
        return b"%PDF-1.4 verified official issuer", url, False

    monkeypatch.setattr(ingestion, "_fetch_result_payload", official_pdf)
    monkeypatch.setattr(ingestion, "_pdf_text", lambda raw: ENGLISH_Q3_NOTICE)

    first = asyncio.run(
        ingestion.refresh_official_distributions(repo, target_date="2026-11-19")
    )
    second = asyncio.run(
        ingestion.refresh_official_distributions(repo, target_date="2026-11-19")
    )
    assert first["status"] == "ok"
    assert first["rows_written"] == 1
    assert first["review_required"] == 0
    assert second["status"] == "ok"
    assert second["rows_written"] == 0
    assert second["unchanged"] == 1
    assert repo.writes == 1
    assert repo.actions[0]["ex_date"] == "2026-11-18"


def test_q3_cvm_r2_fallback_ingests_one_verified_action(monkeypatch):
    """A Cloudflare 526 must not suppress Q3 JCP when pinned CVM bytes exist."""
    repo = MemoryRepository([
        notice(
            "official-q3-ioe", Q3_URL, "2026-11-12",
            title="Notice to Shareholders - Interest on Equity",
        ),
    ])
    bucket = object()

    async def tls_526(url, **kwargs):
        assert url == Q3_URL
        raise RuntimeError("Bemobi IR HTTP 526")

    async def pinned_copy(found_bucket, kind):
        assert found_bucket is bucket
        assert kind == "jcp"
        return b"%PDF-1.4 verified CVM bytes", ingestion.Q3_JCP_URL

    monkeypatch.setattr(ingestion, "_fetch_result_payload", tls_526)
    monkeypatch.setattr(ingestion, "read_verified_q3_document", pinned_copy)
    monkeypatch.setattr(ingestion, "_pdf_text", lambda raw: ENGLISH_Q3_NOTICE)

    first = asyncio.run(ingestion.refresh_official_distributions(
        repo, target_date="2026-11-20", archive_bucket=bucket,
    ))
    second = asyncio.run(ingestion.refresh_official_distributions(
        repo, target_date="2026-11-20", archive_bucket=bucket,
    ))
    assert first["status"] == "ok" and first["rows_written"] == 1
    assert second["rows_written"] == 0 and second["unchanged"] == 1
    assert repo.writes == 1
    assert repo.documents[0]["source_code"] == "CVM"
    assert repo.documents[0]["url"] == ingestion.Q3_JCP_URL
    assert repo.documents[0]["metadata"]["validation"] == "OFFICIAL_CVM_Q3_R2_SHA256"


def test_other_notices_must_not_substitute_pinned_q3_cvm_document(monkeypatch):
    repo = MemoryRepository([
        notice(
            "other-notice", Q3_URL, "2026-11-13",
            title="Notice to Shareholders - Interest on Equity",
        ),
    ])

    async def tls_526(url, **kwargs):
        raise RuntimeError("Bemobi IR HTTP 526")

    async def forbidden_copy(*args, **kwargs):
        raise AssertionError("Other filings must not use the Q3 mirror")

    monkeypatch.setattr(ingestion, "_fetch_result_payload", tls_526)
    monkeypatch.setattr(ingestion, "read_verified_q3_document", forbidden_copy)
    result = asyncio.run(ingestion.refresh_official_distributions(
        repo, target_date="2026-11-20", archive_bucket=object(),
    ))
    assert result["rows_written"] == 0
    assert result["review_required"] == 1

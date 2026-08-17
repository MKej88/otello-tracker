import csv
import io
import zipfile

from app.bemobi.cvm_ipe import (
    BEMOBI_CNPJ,
    BEMOBI_CVM_CODE,
    bemobi_cvm_news_status,
    classify_cvm_ipe_record,
    collect_bemobi_cvm_news,
    list_bemobi_news,
    parse_cvm_ipe_archive,
    years_for_refresh,
)
from app.db.connection import get_connection
from app.db.migration_runner import init_database


FIELDS = [
    "CNPJ_Companhia",
    "Nome_Companhia",
    "Codigo_CVM",
    "Data_Referencia",
    "Categoria",
    "Tipo",
    "Especie",
    "Assunto",
    "Data_Entrega",
    "Tipo_Apresentacao",
    "Protocolo_Entrega",
    "Versao",
    "Link_Download",
]


def _row(**overrides):
    row = {
        "CNPJ_Companhia": BEMOBI_CNPJ,
        "Nome_Companhia": "BEMOBI MOBILE TECH S.A.",
        "Codigo_CVM": BEMOBI_CVM_CODE,
        "Data_Referencia": "2026-08-11",
        "Categoria": "Comunicado ao Mercado",
        "Tipo": "Outros Comunicados Não Considerados Fatos Relevantes",
        "Especie": "",
        "Assunto": "Reeleição de membros da diretoria",
        "Data_Entrega": "2026-08-11",
        "Tipo_Apresentacao": "AP - Apresentação",
        "Protocolo_Entrega": "025500IPE110820260100000001-00",
        "Versao": "1",
        "Link_Download": "https://www.rad.cvm.gov.br/ENET/frmDownloadDocumento.aspx?numProtocolo=1556000&numSequencia=1080700&numVersao=1",
    }
    row.update(overrides)
    return row


def _archive(rows) -> bytes:
    text = io.StringIO()
    writer = csv.DictWriter(text, fieldnames=FIELDS, delimiter=";", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    raw = text.getvalue().encode("cp1252")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("ipe_cia_aberta_2026.csv", raw)
    return buffer.getvalue()


def _fixture_archive() -> bytes:
    rows = [
        _row(
            Categoria="Dados Econômico-Financeiros",
            Tipo="Press-release",
            Assunto="Release 2T26 / 2Q26",
            Protocolo_Entrega="result-1",
        ),
        _row(
            Categoria="Comunicado ao Mercado",
            Assunto="Aquisição de 100% da 7AZ Softwares S.A.",
            Protocolo_Entrega="ma-1",
        ),
        _row(
            Categoria="Fato Relevante",
            Tipo="",
            Assunto="6o programa de recompra de ações - Inclusão de instituições financeiras intermediárias",
            Protocolo_Entrega="buyback-1",
        ),
        _row(
            Categoria="Aviso aos Acionistas",
            Tipo="Outros avisos",
            Assunto="Dividendos/Juros sobre Capital Próprio",
            Tipo_Apresentacao="AP - Apresentação",
            Protocolo_Entrega="jcp-notice-v1",
            Versao="1",
            Link_Download="https://www.rad.cvm.gov.br/ENET/frmDownloadDocumento.aspx?numProtocolo=1556010&numSequencia=1080716&numVersao=1",
        ),
        _row(
            Categoria="Aviso aos Acionistas",
            Tipo="Outros avisos",
            Assunto="Dividendos/Juros sobre Capital Próprio",
            Tipo_Apresentacao="RE - Reapresentação Espontânea",
            Protocolo_Entrega="jcp-notice-v2",
            Versao="2",
            Data_Entrega="2026-08-12",
            Link_Download="https://www.rad.cvm.gov.br/ENET/frmDownloadDocumento.aspx?numProtocolo=1556263&numSequencia=1080969&numVersao=2",
        ),
        _row(
            Categoria="Reunião da Administração",
            Tipo="Conselho de Administração",
            Especie="Ata",
            Assunto="deliberar sobre a declaração, distribuição e o pagamento de juros sobre o capital próprio",
            Protocolo_Entrega="board-jcp-1",
        ),
        _row(
            CNPJ_Companhia="00.000.000/0001-00",
            Nome_Companhia="OUTRA COMPANHIA S.A.",
            Codigo_CVM="99999",
            Categoria="Fato Relevante",
            Assunto="Aquisição de empresa",
            Protocolo_Entrega="other-company",
        ),
    ]
    return _archive(rows)


def test_cvm_archive_parser_uses_official_columns_and_filters_bemobi() -> None:
    records = parse_cvm_ipe_archive(_fixture_archive(), year=2026)
    assert len(records) == 6
    assert {record.cnpj for record in records} == {BEMOBI_CNPJ}
    assert {record.cvm_code for record in records} == {BEMOBI_CVM_CODE}

    categories = {}
    for record in records:
        category, review, _ = classify_cvm_ipe_record(record)
        categories[record.protocol] = (category, review)
    assert categories["result-1"] == ("RESULTS", False)
    assert categories["ma-1"] == ("M_AND_A", False)
    assert categories["buyback-1"] == ("BUYBACK", False)
    assert categories["jcp-notice-v2"] == ("JCP", True)
    assert categories["board-jcp-1"] == ("JCP", False)


def test_external_id_does_not_collide_when_cvm_protocol_is_reused() -> None:
    payload = _archive(
        [
            _row(
                Protocolo_Entrega="same-protocol",
                Assunto="Primeira comunicação",
                Link_Download="https://www.rad.cvm.gov.br/ENET/frmDownloadDocumento.aspx?numProtocolo=100&numSequencia=1&numVersao=1",
            ),
            _row(
                Protocolo_Entrega="same-protocol",
                Assunto="Segunda comunicação",
                Link_Download="https://www.rad.cvm.gov.br/ENET/frmDownloadDocumento.aspx?numProtocolo=100&numSequencia=2&numVersao=1",
            ),
        ]
    )
    records = parse_cvm_ipe_archive(payload, year=2026)
    assert len(records) == 2
    assert records[0].protocol == records[1].protocol
    assert records[0].external_id != records[1].external_id


def test_cvm_collector_archives_versions_but_lists_latest_only(tmp_path, monkeypatch) -> None:
    database = str(tmp_path / "cvm-news.db")
    init_database(database)
    payload = _fixture_archive()
    monkeypatch.setattr(
        "app.bemobi.cvm_ipe.download_cvm_ipe_year",
        lambda year, timeout=45: payload,
    )

    result = collect_bemobi_cvm_news(database, years=[2026])
    assert result["errors"] == []
    assert result["discovered_bemobi_rows"] == 6
    assert result["relevant_rows"] == 6
    assert result["archived"] == 6
    assert result["latest_versions"] == 5
    assert result["requires_review"] == 1
    assert result["categories"] == {
        "BUYBACK": 1,
        "JCP": 2,
        "M_AND_A": 1,
        "RESULTS": 1,
    }

    second = collect_bemobi_cvm_news(database, years=[2026])
    assert second["archived"] == 6

    status = bemobi_cvm_news_status(database)
    assert status["status"] == "ok"
    assert status["count"] == 5
    assert status["all_versions"] == 6
    assert status["requires_review"] == 1

    latest = list_bemobi_news(database, limit=20)
    assert latest["count"] == 5
    assert all(item["is_latest_version"] for item in latest["items"])
    assert len([item for item in latest["items"] if item["category"] == "JCP"]) == 2

    all_versions = list_bemobi_news(database, limit=20, include_superseded=True)
    assert all_versions["count"] == 6
    assert any(item["processing_status"] == "IGNORED" for item in all_versions["items"])

    with get_connection(database) as connection:
        bodies = connection.execute(
            """
            SELECT COUNT(*) AS n
            FROM source_documents sd JOIN sources s ON s.id = sd.source_id
            WHERE s.code = 'CVM' AND sd.document_type = 'CVM_IPE_METADATA'
              AND sd.metadata_json LIKE '%\"document_body_persisted\": true%'
            """
        ).fetchone()["n"]
        assert bodies == 0


def test_refresh_years_backfill_missing_history_and_keep_rolling_years(tmp_path) -> None:
    database = str(tmp_path / "years.db")
    init_database(database)
    assert years_for_refresh(database, target_year=2026) == [2021, 2022, 2023, 2024, 2025, 2026]

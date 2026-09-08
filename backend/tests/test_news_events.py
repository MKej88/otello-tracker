import asyncio

from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.news_events import (
    _classification,
    _news_item,
    _safe_url,
    news_events_dashboard,
)


def test_board_meeting_without_material_analysis_needs_review() -> None:
    classification = _classification(
        "CORPORATE",
        "NONE",
        "PARSED",
        {"cvm_category": "Reunião da Administração"},
    )
    assert classification == (
        "REVIEW",
        "Dokumentet er ikke ferdig analysert, eller mangler en konkret begrunnelse.",
        None,
    )


def test_missing_analysis_reason_falls_back_to_review() -> None:
    classification, _, _ = _classification("JCP", "POTENTIAL", "PARSED", {})
    assert classification == "REVIEW"


def test_explicit_jcp_can_be_confirmed_important() -> None:
    classification, reason, effect = _classification(
        "JCP",
        "DIRECT",
        "PARSED",
        {"classification_reason": "CVM metadata explicitly mentions JCP"},
    )
    assert classification == "CONFIRMED_IMPORTANT"
    assert reason == "Dokumentdata identifiserer en konkret JCP-hendelse."
    assert effect is not None


def test_explicit_acquisition_can_be_confirmed_important() -> None:
    classification, _, _ = _classification(
        "M_AND_A",
        "POTENTIAL",
        "PARSED",
        {"classification_reason": "CVM subject explicitly describes an acquisition"},
    )
    assert classification == "CONFIRMED_IMPORTANT"


def test_only_http_sources_are_exposed_as_links() -> None:
    assert (
        _safe_url("https://example.com/report.pdf") == "https://example.com/report.pdf"
    )
    assert _safe_url("javascript:alert(1)") is None
    assert _safe_url(None) is None


def test_existing_and_future_bemobi_news_are_rendered_in_english() -> None:
    item = _news_item(
        {
            "id": 1,
            "symbol": "BMOB3",
            "headline": "Fato Relevante — Programa de Recompra de Ações",
            "summary": "Categoria: Fato Relevante",
            "category": "BUYBACK",
            "nav_impact": "POTENTIAL",
            "metadata_json": (
                '{"cvm_category":"Fato Relevante",'
                '"cvm_subject":"Programa de Recompra de Ações"}'
            ),
        }
    )

    assert item["headline"] == "Material fact — Share buyback program"
    assert item["summary"] == (
        "Filing type: Material fact | Subject: Share buyback program | "
        "See the official CVM filing for full details."
    )
    assert item["nav_impact"] == "POTENTIAL"


def test_jcp_uses_precise_label_and_exposes_nav_impact() -> None:
    item = _news_item(
        {
            "id": 2,
            "symbol": "BMOB3",
            "headline": "Juros sobre capital próprio",
            "summary": None,
            "category": "JCP",
            "nav_impact": "DIRECT",
            "processing_status": "PARSED",
            "metadata_json": (
                '{"classification_reason":"CVM metadata explicitly mentions JCP"}'
            ),
        }
    )

    assert item["category_label"] == "JCP"
    assert item["nav_impact"] == "DIRECT"
    assert item["importance"] == "HIGH"
    assert item["classification"] == "CONFIRMED_IMPORTANT"


def test_news_events_dashboard_is_safe_on_empty_database(tmp_path) -> None:
    database = str(tmp_path / "news-events.db")
    init_database(database)
    result = asyncio.run(
        news_events_dashboard(
            database,
            as_of_date="2026-08-27",
        )
    )

    assert result == {
        "ready": True,
        "as_of_date": "2026-08-27",
        "news": [],
        "events": [],
        "counts": {"news": 0, "events": 0},
    }


def test_news_uses_document_date_when_news_date_is_missing(tmp_path) -> None:
    database = str(tmp_path / "news-date.db")
    init_database(database)
    with get_connection(database) as connection:
        instrument_id = connection.execute("""
            INSERT INTO instruments(symbol, name, asset_type, currency)
            VALUES ('OTEC', 'Otello', 'EQUITY', 'NOK')
            """).lastrowid
        source_id = connection.execute(
            "SELECT id FROM sources WHERE code='NEWSWEB'"
        ).fetchone()[0]
        document_id = connection.execute(
            """
            INSERT INTO source_documents(
                source_id, document_type, title, published_at, url
            ) VALUES (?, 'NOTICE', 'Viktig melding', '2026-08-26T08:15:00Z',
                      'https://example.com/news')
            """,
            (source_id,),
        ).lastrowid
        connection.execute(
            """
            INSERT INTO company_news(
                issuer_instrument_id, source_document_id, headline,
                published_at, category
            ) VALUES (?, ?, 'Viktig melding', NULL, 'CORPORATE')
            """,
            (instrument_id, document_id),
        )
        connection.commit()

    result = asyncio.run(news_events_dashboard(database, as_of_date="2026-08-27"))

    assert result["news"][0]["published_at"] == "2026-08-26T08:15:00Z"


def test_identical_documents_only_create_one_card(tmp_path) -> None:
    database = str(tmp_path / "deduplicated-news.db")
    init_database(database)
    with get_connection(database) as connection:
        instrument_id = connection.execute("""
            INSERT INTO instruments(symbol, name, asset_type, currency)
            VALUES ('BMOB3', 'Bemobi', 'EQUITY', 'BRL')
            """).lastrowid
        source_id = connection.execute(
            "SELECT id FROM sources WHERE code='CVM'"
        ).fetchone()[0]
        for sequence in (1, 2):
            document_id = connection.execute(
                """
                INSERT INTO source_documents(
                    source_id, external_id, document_type, title, published_at,
                    url, metadata_json
                ) VALUES (?, ?, 'CVM_IPE_METADATA', 'Board meeting — Minutes',
                          '2026-08-27', ?, ?)
                """,
                (
                    source_id,
                    f"meeting-{sequence}",
                    f"https://example.com/meeting-{sequence}",
                    '{"logical_key":"same-meeting","is_latest_version":true}',
                ),
            ).lastrowid
            connection.execute(
                """
                INSERT INTO company_news(
                    issuer_instrument_id, source_document_id, headline,
                    published_at, category, processing_status
                ) VALUES (?, ?, 'Board meeting — Minutes', '2026-08-27',
                          'CORPORATE', 'PARSED')
                """,
                (instrument_id, document_id),
            )
        connection.commit()

    result = asyncio.run(news_events_dashboard(database, as_of_date="2026-08-27"))

    assert len(result["news"]) == 1
    assert result["news"][0]["classification"] == "INFORMATION"

import asyncio

from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.news_events import _importance, _news_item, _safe_url, news_events_dashboard


def test_importance_is_factual_and_deterministic() -> None:
    assert _importance("RESULTS", "NONE") == "HIGH"
    assert _importance("BUYBACK", "NONE") == "MEDIUM"
    assert _importance("CORPORATE", "NONE") == "LOW"
    assert _importance("OTHER", "DIRECT") == "MEDIUM"


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
            "metadata_json": "{}",
        }
    )

    assert item["category_label"] == "JCP"
    assert item["nav_impact"] == "DIRECT"
    assert item["importance"] == "HIGH"


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
        "media_status": {
            "available": False,
            "status": None,
            "window_days": 30,
        },
    }


def test_news_events_exposes_latest_bemobi_media_refresh_status(tmp_path) -> None:
    database = str(tmp_path / "media-status.db")
    init_database(database)
    with get_connection(database) as connection:
        connection.execute(
            """
            INSERT INTO job_runs(
                job_name, started_at, finished_at, status,
                records_written, error_message, metadata_json
            ) VALUES (?, ?, ?, 'PARTIAL', 3, ?, ?)
            """,
            (
                "bemobi_media_refresh",
                "2026-09-04T09:00:00Z",
                "2026-09-04T09:00:05Z",
                "InfoMoney HTTP 503",
                (
                    '{"feeds_checked":5,"candidates":11,"written":3,'
                    '"skipped_existing":6,"window_days":30,'
                    '"initial_backfill":true,"article_limit":24,'
                    '"feed_errors":[{"source":"InfoMoney","error":"HTTP 503"}],'
                    '"translation_errors":[]}'
                ),
            ),
        )
        connection.commit()

    result = asyncio.run(news_events_dashboard(database, as_of_date="2026-09-04"))
    status = result["media_status"]

    assert status["available"] is True
    assert status["status"] == "PARTIAL"
    assert status["finished_at"] == "2026-09-04T09:00:05Z"
    assert status["feeds_checked"] == 5
    assert status["candidates"] == 11
    assert status["written"] == 3
    assert status["skipped_existing"] == 6
    assert status["error_count"] == 1
    assert status["initial_backfill"] is True
    assert status["article_limit"] == 24
    assert status["window_days"] == 30


def test_news_uses_document_date_when_news_date_is_missing(tmp_path) -> None:
    database = str(tmp_path / "news-date.db")
    init_database(database)
    with get_connection(database) as connection:
        instrument_id = connection.execute(
            """
            INSERT INTO instruments(symbol, name, asset_type, currency)
            VALUES ('OTEC', 'Otello', 'EQUITY', 'NOK')
            """
        ).lastrowid
        source_id = connection.execute(
            """
            INSERT INTO sources(code, name, source_type)
            VALUES ('NEWS_TEST', 'Testkilde', 'OTHER')
            """
        ).lastrowid
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

    result = asyncio.run(
        news_events_dashboard(database, as_of_date="2026-08-27")
    )

    assert result["news"][0]["published_at"] == "2026-08-26T08:15:00Z"

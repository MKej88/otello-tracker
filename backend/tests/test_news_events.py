import asyncio

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

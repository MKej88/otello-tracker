from fastapi.testclient import TestClient

from app.main import app
from app.settings import settings


def test_bemobi_news_api_is_safe_on_empty_database(tmp_path) -> None:
    previous_path = settings.database_path
    settings.database_path = str(tmp_path / "bemobi-news-api.db")
    try:
        with TestClient(app) as client:
            news = client.get("/api/bemobi/news")
            assert news.status_code == 200
            assert news.json() == {"count": 0, "items": []}

            status = client.get("/api/bemobi/news/status")
            assert status.status_code == 200
            assert status.json() == {"status": "empty", "count": 0}

            health = client.get("/api/health")
            assert health.status_code == 200
            assert health.json()["version"] == "0.9.0"
    finally:
        settings.database_path = previous_path


def test_bemobi_news_api_validates_limit() -> None:
    with TestClient(app) as client:
        response = client.get("/api/bemobi/news?limit=0")
        assert response.status_code == 422

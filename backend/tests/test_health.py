from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200

    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "otello-api"


def test_dashboard_summary() -> None:
    response = client.get("/api/dashboard/summary")
    assert response.status_code == 200
    payload = response.json()
    assert "ready" in payload
    assert "data_status" in payload
    # A fresh smoke-test database must never fall back to invented demo values.
    if not payload["ready"]:
        assert payload["data_status"] == "not_ready"
        assert "nav_per_share" not in payload


def test_date_query_rejects_nonexistent_calendar_date() -> None:
    response = client.get("/api/buybacks/forecast?as_of_date=2026-02-30")

    assert response.status_code == 422

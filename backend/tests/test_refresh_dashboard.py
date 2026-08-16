from app.jobs.refresh_dashboard import _safe_step, _staleness, run_refresh


def test_safe_step_records_provider_error_and_continues():
    errors: list[dict[str, str]] = []

    def fail():
        raise RuntimeError("provider unavailable")

    result = _safe_step("provider", fail, errors)
    assert result is None
    assert errors == [{"step": "provider", "error": "provider unavailable"}]


def test_staleness_uses_dashboard_as_of_date():
    assert _staleness({"as_of_date": "2026-08-14"}, "2026-08-17") == {
        "calendar_days": 3,
        "stale": False,
    }
    assert _staleness({"as_of_date": "2026-08-14"}, "2026-08-18") == {
        "calendar_days": 4,
        "stale": True,
    }
    assert _staleness({"ready": False}, "2026-08-18") == {
        "calendar_days": None,
        "stale": True,
    }


def test_refresh_without_network_is_safe_on_fresh_database(tmp_path):
    db = str(tmp_path / "refresh.db")
    result = run_refresh(
        db,
        target_date="2026-08-14",
        fetch_ecb=False,
        fetch_b3=False,
        fetch_buybacks=False,
    )

    assert result["status"] == "not_ready"
    assert result["target_date"] == "2026-08-14"
    assert result["steps"]["ecb"] == {"skipped": True}
    assert result["steps"]["b3"] == {"skipped": True}
    assert result["steps"]["buybacks"] == {"skipped": True}
    assert result["dashboard"]["ready"] is False
    assert result["market_data"]["status"] in {"empty", "degraded", "ok"}

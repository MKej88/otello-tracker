from datetime import date as real_date

import app.jobs.refresh_dashboard_v2 as refresh_v2
from app.db.migration_runner import init_database


def test_live_full_refresh_disables_annual_b3_download(tmp_path, monkeypatch) -> None:
    database = str(tmp_path / "live.db")
    init_database(database)
    calls = {}

    class FixedDate(real_date):
        @classmethod
        def today(cls):
            return cls(2026, 8, 17)

    monkeypatch.setattr(refresh_v2, "date", FixedDate)
    monkeypatch.setattr(
        refresh_v2,
        "market_activity_status",
        lambda *_args, **_kwargs: {"status": "ok", "count": 600, "to": "2026-08-14"},
    )
    monkeypatch.setattr(refresh_v2, "activity_check_done", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(refresh_v2, "refresh_otec_intraday_price", lambda *_args, **_kwargs: {"status": "ok"})
    monkeypatch.setattr(
        refresh_v2,
        "refresh_bmob3_official_close",
        lambda *_args, **kwargs: calls.setdefault("close_kwargs", kwargs) or {"status": "ok"},
    )
    monkeypatch.setattr(refresh_v2, "maybe_finalize_bmob3_eod", lambda *_args, **_kwargs: {"status": "skipped", "reason": "before_b3_eod_cutoff"})
    monkeypatch.setattr(refresh_v2, "refresh_bmob3_intraday_price", lambda *_args, **_kwargs: {"status": "ok"})
    monkeypatch.setattr(refresh_v2, "sync_current_program_terms", lambda *_args, **_kwargs: {"status": "ok"})

    def fake_core(database_path, **kwargs):
        calls["core_database"] = database_path
        calls["core_kwargs"] = kwargs
        return {"status": "ok", "steps": {}, "source_errors": []}

    monkeypatch.setattr(refresh_v2, "run_core_refresh", fake_core)

    result = refresh_v2.run_refresh(
        database,
        target_date="2026-08-17",
        fetch_b3=True,
        fetch_buybacks=True,
    )

    assert result["status"] == "ok"
    assert calls["close_kwargs"] == {"target_date": "2026-08-17"}
    assert calls["core_kwargs"]["fetch_b3"] is False
    assert calls["core_kwargs"]["fetch_otec_delayed"] is False
    assert result["steps"]["bmob3_delayed"]["status"] == "ok"


def test_historical_full_refresh_keeps_annual_b3_backfill(tmp_path, monkeypatch) -> None:
    database = str(tmp_path / "historical.db")
    init_database(database)
    calls = {}

    class FixedDate(real_date):
        @classmethod
        def today(cls):
            return cls(2026, 8, 17)

    monkeypatch.setattr(refresh_v2, "date", FixedDate)
    monkeypatch.setattr(
        refresh_v2,
        "market_activity_status",
        lambda *_args, **_kwargs: {"status": "ok", "count": 600, "to": "2026-08-14"},
    )
    monkeypatch.setattr(refresh_v2, "activity_check_done", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(refresh_v2, "sync_current_program_terms", lambda *_args, **_kwargs: {"status": "ok"})

    def fake_core(database_path, **kwargs):
        calls["core_kwargs"] = kwargs
        return {"status": "ok", "steps": {}, "source_errors": []}

    monkeypatch.setattr(refresh_v2, "run_core_refresh", fake_core)
    result = refresh_v2.run_refresh(
        database,
        target_date="2026-08-14",
        fetch_b3=True,
        fetch_buybacks=False,
    )

    assert result["status"] == "ok"
    assert calls["core_kwargs"]["fetch_b3"] is True
    assert result["steps"]["bmob3_official_close"]["reason"] == "live_lightweight_source_not_used_for_historical_target"

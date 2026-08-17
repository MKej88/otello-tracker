from datetime import date as real_date

import app.jobs.fast_refresh as fast
from app.db.migration_runner import init_database
from app.history import seed_curated_history


def test_fast_refresh_uses_incremental_sources_and_skips_heavy_providers(tmp_path, monkeypatch) -> None:
    database = str(tmp_path / "fast.db")
    init_database(database)
    seed_curated_history(database)
    calls: dict[str, object] = {}

    class FixedDate(real_date):
        @classmethod
        def today(cls):
            return cls(2026, 8, 17)

    monkeypatch.setattr(fast, "date", FixedDate)
    monkeypatch.setattr(
        fast,
        "market_activity_status",
        lambda *_args, **_kwargs: {"status": "ok", "count": 600, "to": "2026-08-14"},
    )
    monkeypatch.setattr(fast, "activity_check_done", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        fast,
        "refresh_otec_delayed_price",
        lambda *_args, **_kwargs: calls.setdefault("otec", True) or {"status": "ok"},
    )

    def news_history(*_args, **kwargs):
        calls["history_kwargs"] = kwargs
        return {"archived": 0, "errors": []}

    def news_buybacks(*_args, **kwargs):
        calls["buyback_kwargs"] = kwargs
        return {"ingested": 0, "errors": []}

    monkeypatch.setattr(fast, "collect_newsweb_history", news_history)
    monkeypatch.setattr(fast, "collect_newsweb_buybacks", news_buybacks)
    monkeypatch.setattr(fast, "sync_newsweb_daily_buyback_cash", lambda *_args, **_kwargs: {"weeks_synced": 0})
    monkeypatch.setattr(fast, "sync_current_program_terms", lambda *_args, **_kwargs: {"status": "ok"})
    monkeypatch.setattr(fast, "rebuild_daily_cash", lambda *_args, **_kwargs: {"written": 1})
    monkeypatch.setattr(fast, "_latest_otec_date", lambda *_args, **_kwargs: "2026-08-17")
    monkeypatch.setattr(
        fast,
        "rebuild_daily_core_nav",
        lambda *_args, **kwargs: calls.setdefault("core_nav_kwargs", kwargs) or {"written": 1},
    )
    monkeypatch.setattr(
        fast,
        "rebuild_daily_full_nav",
        lambda *_args, **kwargs: calls.setdefault("full_nav_kwargs", kwargs) or {"written": 1},
    )
    monkeypatch.setattr(
        fast,
        "dashboard_summary",
        lambda *_args, **_kwargs: {"ready": True, "data_status": "BACKFILLED", "as_of_date": "2026-08-17"},
    )

    result = fast.run_fast_refresh(database, target_date="2026-08-17")

    assert result["refresh_mode"] == "fast"
    assert result["status"] == "ok"
    assert calls["history_kwargs"] == {"to_date": "2026-08-17"}
    # Important: no explicit historical from_date. The NewsWeb collector selects its own
    # latest-21-day overlap, so the 30-minute cycle does not refetch from 2023.
    assert calls["buyback_kwargs"] == {"to_date": "2026-08-17"}
    assert calls["core_nav_kwargs"] == {
        "start_date": "2026-08-17",
        "end_date": "2026-08-17",
    }
    assert calls["full_nav_kwargs"] == {
        "start_date": "2026-08-17",
        "end_date": "2026-08-17",
    }

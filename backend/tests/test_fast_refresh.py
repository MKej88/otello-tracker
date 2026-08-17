from datetime import date as real_date, datetime
from zoneinfo import ZoneInfo

import app.jobs.fast_refresh as fast
from app.db.migration_runner import init_database
from app.history import seed_curated_history


def _patch_common_sources(monkeypatch, calls: dict[str, object]) -> None:
    monkeypatch.setattr(
        fast,
        "market_activity_status",
        lambda *_args, **_kwargs: {"status": "ok", "count": 600, "to": "2026-08-14"},
    )
    monkeypatch.setattr(fast, "activity_check_done", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        fast,
        "refresh_otec_intraday_price",
        lambda *_args, **_kwargs: calls.setdefault("otec_intraday", True) or {"status": "ok"},
    )
    monkeypatch.setattr(
        fast,
        "maybe_finalize_otec_eod",
        lambda *_args, **kwargs: calls.setdefault("otec_eod_kwargs", kwargs) or {"status": "skipped"},
    )
    monkeypatch.setattr(
        fast,
        "refresh_bmob3_intraday_price",
        lambda *_args, **_kwargs: calls.setdefault("bmob3_intraday", True) or {"status": "ok"},
    )
    monkeypatch.setattr(
        fast,
        "maybe_finalize_bmob3_eod",
        lambda *_args, **kwargs: calls.setdefault("bmob3_eod_kwargs", kwargs) or {"status": "skipped"},
    )

    def news_history(*_args, **kwargs):
        calls["history_kwargs"] = kwargs
        return {"archived": 0, "errors": []}

    def news_buybacks(*_args, **kwargs):
        calls["buyback_kwargs"] = kwargs
        return {"ingested": 0, "errors": []}

    monkeypatch.setattr(fast, "collect_newsweb_history", news_history)
    monkeypatch.setattr(fast, "collect_newsweb_buybacks", news_buybacks)
    monkeypatch.setattr(
        fast,
        "sync_newsweb_daily_buyback_cash",
        lambda *_args, **_kwargs: {"weeks_synced": 0},
    )
    monkeypatch.setattr(
        fast,
        "sync_current_program_terms",
        lambda *_args, **_kwargs: {"status": "ok"},
    )
    monkeypatch.setattr(
        fast,
        "rebuild_daily_cash_if_changed",
        lambda *_args, **_kwargs: {"written": 1, "skipped": False},
    )


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
    _patch_common_sources(monkeypatch, calls)
    monkeypatch.setattr(fast, "_latest_otec_date", lambda *_args, **_kwargs: "2026-08-17")
    monkeypatch.setattr(fast, "_has_market_price_for_date", lambda *_args, **_kwargs: False)
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
        lambda *_args, **_kwargs: {
            "ready": True,
            "data_status": "BACKFILLED",
            "as_of_date": "2026-08-17",
        },
    )

    now = datetime(2026, 8, 17, 12, 0, tzinfo=ZoneInfo("Europe/Oslo"))
    result = fast.run_fast_refresh(database, target_date="2026-08-17", now=now)

    assert result["refresh_mode"] == "fast"
    assert result["status"] == "ok"
    assert result["live_calendar_snapshot"] is False
    assert calls["otec_intraday"] is True
    assert calls["bmob3_intraday"] is True
    assert calls["otec_eod_kwargs"] == {"target_date": "2026-08-17", "now": now}
    assert calls["bmob3_eod_kwargs"] == {"now": now}
    assert calls["history_kwargs"] == {"to_date": "2026-08-17"}
    assert calls["buyback_kwargs"] == {"to_date": "2026-08-17"}
    assert calls["core_nav_kwargs"] == {
        "start_date": "2026-08-17",
        "end_date": "2026-08-17",
    }
    assert calls["full_nav_kwargs"] == {
        "start_date": "2026-08-17",
        "end_date": "2026-08-17",
    }


def test_live_bmob3_quote_can_advance_nav_date_before_otec_trades(tmp_path, monkeypatch) -> None:
    database = str(tmp_path / "bmob3-live-date.db")
    init_database(database)
    seed_curated_history(database)
    calls: dict[str, object] = {}

    class FixedDate(real_date):
        @classmethod
        def today(cls):
            return cls(2026, 8, 17)

    monkeypatch.setattr(fast, "date", FixedDate)
    _patch_common_sources(monkeypatch, calls)
    monkeypatch.setattr(fast, "_latest_otec_date", lambda *_args, **_kwargs: "2026-08-14")
    monkeypatch.setattr(fast, "_has_market_price_for_date", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(fast, "_ona_has_date", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        fast,
        "rebuild_core_nav_for_date",
        lambda *_args, **kwargs: calls.setdefault("calendar_core_kwargs", kwargs) or {"written": 1},
    )
    monkeypatch.setattr(
        fast,
        "rebuild_daily_core_nav",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("historical OTEC-date rebuild must not be used for live calendar snapshot")
        ),
    )
    monkeypatch.setattr(
        fast,
        "rebuild_daily_full_nav",
        lambda *_args, **kwargs: calls.setdefault("full_nav_kwargs", kwargs) or {"written": 1},
    )
    monkeypatch.setattr(
        fast,
        "dashboard_summary",
        lambda *_args, **_kwargs: {
            "ready": True,
            "data_status": "BACKFILLED",
            "as_of_date": "2026-08-17",
        },
    )

    result = fast.run_fast_refresh(database, target_date="2026-08-17")

    assert result["live_calendar_snapshot"] is True
    assert result["latest_otec_date"] == "2026-08-14"
    assert result["latest_market_date"] == "2026-08-17"
    assert calls["calendar_core_kwargs"] == {"as_of_date": "2026-08-17"}
    assert calls["full_nav_kwargs"] == {
        "start_date": "2026-08-17",
        "end_date": "2026-08-17",
    }


def test_eod_result_skips_intraday_when_session_is_finalized() -> None:
    assert fast._eod_is_authoritative_for_cycle({"status": "ok"}) is True
    assert fast._eod_is_authoritative_for_cycle({"status": "no_trade"}) is True
    assert fast._eod_is_authoritative_for_cycle(
        {"status": "skipped", "reason": "eod_already_finalized"}
    ) is True
    assert fast._eod_is_authoritative_for_cycle(
        {"status": "skipped", "reason": "before_eod_cutoff"}
    ) is False
    assert fast._eod_is_authoritative_for_cycle(None) is False


def test_bmob3_eod_priority_skips_intraday(tmp_path, monkeypatch) -> None:
    database = str(tmp_path / "bmob3-eod.db")
    init_database(database)
    seed_curated_history(database)

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
    monkeypatch.setattr(fast, "maybe_finalize_otec_eod", lambda *_args, **_kwargs: {"status": "ok"})
    monkeypatch.setattr(fast, "maybe_finalize_bmob3_eod", lambda *_args, **_kwargs: {"status": "ok"})
    monkeypatch.setattr(
        fast,
        "refresh_bmob3_intraday_price",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("intraday BMOB3 not expected")
        ),
    )
    monkeypatch.setattr(fast, "collect_newsweb_history", lambda *_args, **_kwargs: {"errors": []})
    monkeypatch.setattr(fast, "collect_newsweb_buybacks", lambda *_args, **_kwargs: {"errors": []})
    monkeypatch.setattr(fast, "sync_newsweb_daily_buyback_cash", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(fast, "sync_current_program_terms", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(fast, "rebuild_daily_cash_if_changed", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(fast, "_latest_otec_date", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(fast, "_has_market_price_for_date", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(fast, "dashboard_summary", lambda *_args, **_kwargs: {"ready": False})

    result = fast.run_fast_refresh(database, target_date="2026-08-17")
    assert result["steps"]["bmob3_delayed"] == {
        "skipped": True,
        "reason": "eod_finalized_for_session",
    }

from datetime import date as real_date

import app.jobs.refresh_dashboard as refresh_module
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
        fetch_bemobi_news=False,
    )

    assert result["status"] == "not_ready"
    assert result["target_date"] == "2026-08-14"
    assert result["steps"]["ecb"] == {"skipped": True}
    assert result["steps"]["b3"] == {"skipped": True}
    assert result["steps"]["otec_delayed"] == {
        "skipped": True,
        "reason": "live_source_not_used_for_historical_target",
    }
    assert result["steps"]["bemobi_cvm_news"] == {"skipped": True}
    assert result["steps"]["newsweb_history"] == {"skipped": True}
    assert result["steps"]["newsweb_2021_events"] == {"skipped": True}
    assert result["steps"]["buybacks"] == {"skipped": True}
    assert result["dashboard"]["ready"] is False
    assert result["market_data"]["status"] in {"empty", "degraded", "ok"}


def test_refresh_runs_delayed_otec_only_for_live_target(tmp_path, monkeypatch):
    db = str(tmp_path / "refresh-otec-live.db")
    called: list[str] = []

    class FixedDate(real_date):
        @classmethod
        def today(cls):
            return cls(2026, 8, 17)

    monkeypatch.setattr(refresh_module, "date", FixedDate)
    monkeypatch.setattr(
        refresh_module,
        "refresh_otec_delayed_price",
        lambda *args, **kwargs: called.append("otec") or {
            "status": "ok",
            "selected": "CURRENT_TRADING_DAY",
            "price_nok": "17.20",
        },
    )

    result = run_refresh(
        db,
        target_date="2026-08-17",
        fetch_ecb=False,
        fetch_b3=False,
        fetch_buybacks=False,
        fetch_bemobi_news=False,
    )

    assert called == ["otec"]
    assert result["steps"]["otec_delayed"] == {
        "status": "ok",
        "selected": "CURRENT_TRADING_DAY",
        "price_nok": "17.20",
    }


def test_refresh_delayed_otec_failure_is_fail_soft(tmp_path, monkeypatch):
    db = str(tmp_path / "refresh-otec-error.db")

    class FixedDate(real_date):
        @classmethod
        def today(cls):
            return cls(2026, 8, 17)

    monkeypatch.setattr(refresh_module, "date", FixedDate)
    monkeypatch.setattr(
        refresh_module,
        "refresh_otec_delayed_price",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("euronext unavailable")),
    )

    result = run_refresh(
        db,
        target_date="2026-08-17",
        fetch_ecb=False,
        fetch_b3=False,
        fetch_buybacks=False,
        fetch_bemobi_news=False,
    )

    assert result["steps"]["otec_delayed"] is None
    assert {"step": "otec_delayed", "error": "euronext unavailable"} in result["source_errors"]


def test_refresh_runs_verified_2021_events_and_incremental_buybacks(tmp_path, monkeypatch):
    db = str(tmp_path / "refresh-newsweb.db")
    called: list[str] = []
    buyback_kwargs: dict[str, str] = {}

    monkeypatch.setattr(
        refresh_module,
        "collect_newsweb_history",
        lambda *args, **kwargs: {"archived": 1, "errors": []},
    )
    monkeypatch.setattr(
        refresh_module,
        "seed_2021_newsweb_events",
        lambda *args, **kwargs: called.append("2021") or {"buybacks": [1], "missing_fx": []},
    )
    monkeypatch.setattr(refresh_module, "collect_recent_buybacks", lambda *args, **kwargs: {"ok": True})

    def collect_buybacks(*_args, **kwargs):
        buyback_kwargs.update(kwargs)
        return {"errors": [], "ingested": 0}

    monkeypatch.setattr(refresh_module, "collect_newsweb_buybacks", collect_buybacks)
    monkeypatch.setattr(
        refresh_module,
        "sync_newsweb_daily_buyback_cash",
        lambda *args, **kwargs: {"weeks_synced": 0},
    )

    result = run_refresh(
        db,
        target_date="2026-08-14",
        fetch_ecb=False,
        fetch_b3=False,
        fetch_buybacks=True,
        fetch_bemobi_news=False,
    )

    assert called == ["2021"]
    assert buyback_kwargs == {"to_date": "2026-08-14"}
    assert result["steps"]["newsweb_2021_events"] == {"buybacks": [1], "missing_fx": []}
    assert result["steps"]["bemobi_cvm_news"] == {"skipped": True}
    assert result["source_errors"] == []


def test_refresh_runs_incremental_bemobi_cvm_news_as_non_financial_step(tmp_path, monkeypatch):
    db = str(tmp_path / "refresh-bemobi.db")
    called: list[int] = []

    monkeypatch.setattr(
        refresh_module,
        "collect_bemobi_cvm_news_incremental",
        lambda *args, **kwargs: called.append(kwargs["target_year"]) or {
            "archived": 2,
            "errors": [],
            "latest_versions": 2,
        },
    )

    result = run_refresh(
        db,
        target_date="2026-08-14",
        fetch_ecb=False,
        fetch_b3=False,
        fetch_buybacks=False,
        fetch_bemobi_news=True,
    )

    assert called == [2026]
    assert result["steps"]["bemobi_cvm_news"] == {
        "archived": 2,
        "errors": [],
        "latest_versions": 2,
    }
    assert result["source_errors"] == []

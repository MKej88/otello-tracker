from datetime import date as real_date

import app.jobs.refresh_dashboard_v2 as wrapper


def test_daily_wrapper_refreshes_light_otec_before_core_nav(tmp_path, monkeypatch) -> None:
    database = str(tmp_path / "daily.db")
    order: list[str] = []
    captured_core_kwargs = {}

    class FixedDate(real_date):
        @classmethod
        def today(cls):
            return cls(2026, 8, 17)

    monkeypatch.setattr(wrapper, "date", FixedDate)
    monkeypatch.setattr(
        wrapper,
        "market_activity_status",
        lambda *_args, **_kwargs: {"status": "ok", "count": 600, "to": "2026-08-14"},
    )
    monkeypatch.setattr(wrapper, "activity_check_done", lambda *_args, **_kwargs: True)

    def light_otec(*_args, **_kwargs):
        order.append("otec")
        return {"status": "ok", "feed_mode": "delayed_intraday"}

    def core_refresh(_database_path, **kwargs):
        order.append("core")
        captured_core_kwargs.update(kwargs)
        return {"status": "ok", "steps": {}, "source_errors": [], "dashboard": {"ready": True}}

    monkeypatch.setattr(wrapper, "refresh_otec_intraday_price", light_otec)
    monkeypatch.setattr(wrapper, "run_core_refresh", core_refresh)
    monkeypatch.setattr(
        wrapper,
        "sync_current_program_terms",
        lambda *_args, **_kwargs: {"status": "ok"},
    )

    result = wrapper.run_refresh(
        database,
        target_date="2026-08-17",
        fetch_otec_delayed=True,
        fetch_buybacks=False,
    )

    assert order == ["otec", "core"]
    assert captured_core_kwargs["fetch_otec_delayed"] is False
    assert result["steps"]["otec_delayed"]["feed_mode"] == "delayed_intraday"

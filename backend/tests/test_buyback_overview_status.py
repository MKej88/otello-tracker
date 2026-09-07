from pathlib import Path

from app.buybacks import dashboard


ROOT = Path(__file__).resolve().parents[2]


def test_overview_status_only_returns_fields_used_by_overview(monkeypatch) -> None:
    full_payload = {
        "program": {"cumulative_shares": 123, "progress_pct": 4.5},
        "nav_effect": {"per_share_nok": 0.12},
        "forecast": {"large": [1, 2, 3]},
        "backtest": {"weeks": [1, 2, 3]},
    }
    monkeypatch.setattr(
        dashboard, "buyback_dashboard", lambda *_args, **_kwargs: full_payload
    )

    assert dashboard.buyback_overview_status("ignored.db") == {
        "program": full_payload["program"],
        "nav_effect": full_payload["nav_effect"],
    }


def test_overview_uses_compact_buyback_endpoint_in_both_runtimes() -> None:
    frontend = (ROOT / "frontend/src/OverviewPage.tsx").read_text(encoding="utf-8")
    backend = (ROOT / "backend/app/main.py").read_text(encoding="utf-8")
    worker = (ROOT / "cloudflare/src/app.py").read_text(encoding="utf-8")

    assert '"/api/buybacks/overview-status"' in frontend
    assert '@app.get("/api/buybacks/overview-status")' in backend
    assert '@app.get("/api/buybacks/overview-status")' in worker

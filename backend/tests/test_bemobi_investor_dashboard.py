from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from app.bemobi import dashboard as bemobi_module
from app.db.migration_runner import init_database
from app.history import seed_curated_history
from app.history.distributions import seed_bemobi_distributions


ROOT = Path(__file__).resolve().parents[2]


def _summary() -> dict:
    return {
        "ready": True,
        "data_status": "ESTIMATED",
        "as_of_date": "2026-08-18",
        "bmob3_price": 22.8,
        "brl_nok": 1.9,
        "bemobi_value_mnok": 1418.0,
        "bemobi_shares": 32_719_588,
        "bemobi_ownership_pct": None,
        "bemobi_ownership_quality": "STALE_REPORTED",
        "shares_outstanding": 70_000_000,
        "bmob3_price_source": "B3",
        "bmob3_price_quality": "DIRECT",
        "market_timestamps": {
            "bmob3": {"date": "2026-08-18"},
            "brl_nok": {"date": "2026-08-18"},
        },
    }


def test_bemobi_dashboard_combines_market_ownership_result_and_jcp(tmp_path, monkeypatch) -> None:
    database = str(tmp_path / "bemobi-investor.db")
    init_database(database)
    seed_curated_history(database)
    seed_bemobi_distributions(database)

    monkeypatch.setattr(bemobi_module, "dashboard_summary", lambda _path: _summary())
    monkeypatch.setattr(
        bemobi_module,
        "enrich_dashboard_summary",
        lambda summary, _path: summary,
    )

    result = bemobi_module.bemobi_dashboard(database)

    assert result["ready"] is True
    assert result["market"] == {
        "price_brl": 22.8,
        "price_date": "2026-08-18",
        "price_source": "B3",
        "price_quality": "DIRECT",
        "brl_nok": 1.9,
        "brl_nok_date": "2026-08-18",
    }

    assert result["otello"]["shares"] == 32_719_588
    assert result["otello"]["ownership_pct"] == 38.22
    assert result["otello"]["ownership_source_date"] == "2026-08-19"
    assert result["otello"]["ownership_quality"] == "OFFICIAL_IR_CURRENT"
    assert result["otello"]["bemobi_total_shares"] == 85_608_392
    assert result["otello"]["value_brl_m"] == 22.8 * 32_719_588 / 1_000_000
    assert result["otello"]["value_per_otello_share_nok"] == 1418.0 / 70.0

    latest = result["latest_result"]
    assert latest["period"] == "2Q26"
    assert latest["published_date"] == "2026-08-11"
    assert latest["adjusted_net_revenue_mbrl"] == 227.3
    assert latest["adjusted_ebitda_mbrl"] == 79.4
    assert latest["adjusted_ebitda_margin_pct"] == 34.9
    assert latest["adjusted_net_income_mbrl"] == 45.2
    assert latest["cash_mbrl"] == 328.0

    distribution = result["latest_distribution"]
    assert distribution is not None
    assert distribution["external_action_id"] == "bemobi-2026-08-28-jcp-2q26"
    assert distribution["type"] == "JCP"
    assert distribution["ex_date"] == "2026-08-17"
    assert distribution["payment_date"] == "2026-08-28"
    assert Decimal(str(distribution["gross_per_share_brl"])) == Decimal("0.19178292")
    assert Decimal(str(distribution["net_per_share_brl"])) == Decimal("0.15822091")
    assert abs(distribution["otello_gross_mbrl"] - 6.27505812783696) < 1e-10
    assert abs(distribution["otello_net_mbrl"] - 5.17692298818508) < 1e-10
    assert distribution["source_code"] == "CVM"

    assert result["next_report"]["period"] == "3Q26"
    assert result["next_report"]["date"] is None
    assert result["next_report"]["date_quality"] == "NOT_CONFIRMED"


def test_bemobi_page_is_exposed_in_reference_worker_and_frontend() -> None:
    backend_app = (ROOT / "backend/app/main.py").read_text(encoding="utf-8")
    worker_app = (ROOT / "cloudflare/src/app.py").read_text(encoding="utf-8")
    worker_service = (ROOT / "cloudflare/src/bemobi_dashboard.py").read_text(encoding="utf-8")
    frontend = (ROOT / "frontend/src/App.tsx").read_text(encoding="utf-8")
    page = (ROOT / "frontend/src/BemobiPage.tsx").read_text(encoding="utf-8")

    assert '@app.get("/api/bemobi/dashboard")' in backend_app
    assert '@app.get("/api/bemobi/dashboard")' in worker_app
    assert 'CURRENT_OWNERSHIP' in worker_service
    assert '"ownership_pct": 38.220' in worker_service
    assert 'type View = "Oversikt" | "NAV" | "Tilbakekjøp" | "Bemobi";' in frontend
    assert '{ label: "Bemobi", enabled: true }' in frontend
    assert '<BemobiPage />' in frontend
    assert 'fetch("/api/bemobi/dashboard")' in page
    assert "Ikke bekreftet" in page

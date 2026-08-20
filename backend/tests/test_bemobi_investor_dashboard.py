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


def test_bemobi_dashboard_combines_market_ownership_result_valuation_and_jcp(tmp_path, monkeypatch) -> None:
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

    valuation = result["valuation"]
    assert valuation["period"] == "TTM 3Q25–2Q26"
    assert valuation["adjusted_net_income_ttm_mbrl"] == 184.2
    assert valuation["adjusted_ebitda_ttm_mbrl"] == 283.1
    assert abs(valuation["adjusted_fcf_ttm_mbrl"] - 226.2) < 1e-12
    assert valuation["ebit_ttm_mbrl"] == 175.08
    assert valuation["net_debt_mbrl"] == -287.2
    assert valuation["net_cash_mbrl"] == 287.2
    assert valuation["ev_anchor_period"] == "2Q26"
    assert valuation["ev_anchor_quality"] == "CVM_DERIVED_APPROX"
    assert abs(valuation["market_cap_mbrl"] - 1951.8713376) < 1e-9
    assert abs(valuation["enterprise_value_mbrl"] - 1664.6713376) < 1e-9
    assert abs(valuation["adjusted_eps_ttm_brl"] - 2.1516582159375215) < 1e-12
    assert abs(valuation["pe_ttm"] - 10.596478488599349) < 1e-12
    assert abs(valuation["price_to_ebitda_ttm"] - 6.894635597315435) < 1e-12
    assert abs(valuation["earnings_yield_pct"] - 9.437097438322462) < 1e-12
    assert abs(valuation["adjusted_fcf_yield_pct"] - 11.588878613184262) < 1e-12
    assert abs(valuation["ev_ebit_ttm"] - 9.508061101210874) < 1e-12
    assert [item["multiple"] for item in valuation["scenarios"]] == [12.0, 14.0, 16.0]
    assert abs(valuation["scenarios"][0]["implied_price_brl"] - 25.819898591250258) < 1e-12
    assert abs(valuation["scenarios"][1]["implied_price_brl"] - 30.1232150231253) < 1e-12
    assert abs(valuation["scenarios"][2]["implied_price_brl"] - 34.426531455000344) < 1e-12
    assert len(valuation["source_quarters"]) == 4
    assert valuation["source_quarters"][-1]["period"] == "2Q26"
    assert valuation["source_quarters"][-1]["source_url"]
    assert valuation["source_quarters"][-1]["adjusted_cash_generation_mbrl"] == 64.8

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


def test_bemobi_page_uses_database_facts_in_reference_worker_and_frontend() -> None:
    backend_app = (ROOT / "backend/app/main.py").read_text(encoding="utf-8")
    worker_app = (ROOT / "cloudflare/src/app.py").read_text(encoding="utf-8")
    worker_service = (ROOT / "cloudflare/src/bemobi_dashboard.py").read_text(encoding="utf-8")
    d1_migration = (ROOT / "cloudflare/migrations/0009_bemobi_investor_facts.sql").read_text(
        encoding="utf-8"
    )
    frontend = (ROOT / "frontend/src/App.tsx").read_text(encoding="utf-8")
    page = (ROOT / "frontend/src/BemobiPage.tsx").read_text(encoding="utf-8")

    assert '@app.get("/api/bemobi/dashboard")' in backend_app
    assert '@app.get("/api/bemobi/dashboard")' in worker_app
    assert "latest_bemobi_fact" in worker_service
    assert "load_bemobi_facts" in worker_service
    assert "CURRENT_OWNERSHIP" not in worker_service
    assert "TTM_QUARTERS" not in worker_service
    assert "TTM_EBIT_MBRL" not in worker_service
    assert "NET_DEBT_2Q26_MBRL" not in worker_service
    assert 'VALUATION_MULTIPLES = (12.0, 14.0, 16.0)' in worker_service
    assert "CREATE TABLE bemobi_investor_facts" in d1_migration
    assert "'RESULT', '2Q26'" in d1_migration
    assert "'FORWARD_CONSENSUS', '2026'" in d1_migration
    assert 'type View = "Oversikt" | "NAV" | "Tilbakekjøp" | "Bemobi" | "Konsensus";' in frontend
    assert '{ label: "Bemobi", enabled: true }' in frontend
    assert '<BemobiPage />' in frontend
    assert 'fetch("/api/bemobi/dashboard")' in page
    assert "Verdsettelse nå" in page
    assert "EV / EBIT TTM" in page
    assert "FCF yield (just.)" in page
    assert "Multipelsensitivitet" in page
    assert "Ikke kursmål" in page
    assert "Ikke bekreftet" in page

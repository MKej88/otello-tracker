from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.bemobi import consensus as consensus_module
from app.bemobi.quarter_comparison import build_quarter_comparison
from app.db.connection import get_connection
from app.db.migration_runner import init_database

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "backend/app/db/migrations/0040_bemobi_quarter_actuals.sql"
METRICS = (
    "revenue_mbrl", "adjusted_ebitda_mbrl", "adjusted_net_income_mbrl",
    "ebitda_margin_pct", "payments_revenue_mbrl", "saas_revenue_mbrl",
    "subscriptions_revenue_mbrl", "microfinance_revenue_mbrl", "capex_mbrl",
    "capex_to_sales_pct", "operating_free_cash_flow_mbrl",
)


def test_comparison_returns_all_verified_actuals_without_changing_history(tmp_path, monkeypatch):
    database = str(tmp_path / "actuals.db")
    init_database(database)
    monkeypatch.setattr(consensus_module, "bemobi_dashboard", lambda _path: {"ready": True})
    result = consensus_module.bemobi_consensus(database)
    comparison = result["quarter_comparison"]
    for key, period, expected in (
        ("latest_report", "2Q26", [227.3, 79.4, 45.2, 34.9, 112.0, 46.1, 48.7, 20.5, 14.7, 6.5, 64.8]),
        ("prior_year", "3Q25", [187.5, 62.7, 42.5, 33.4, 73.8, 39.7, 53.0, 20.9, 15.2, 8.1, 47.4]),
    ):
        quarter = comparison[key]
        assert quarter["period"] == period
        assert quarter["source_name"] == "BTG Pactual"
        assert quarter["source_page"] == 3
        assert quarter["source_evidence"] == "PDF_TABLE_VERIFIED"
        assert quarter["published_date"] == "2026-10-08"
        assert quarter["source_url"].endswith(".pdf")
        assert [item["metric"] for item in quarter["metrics"]] == list(METRICS)
        assert [item.get("value_mbrl", item.get("value_pct")) for item in quarter["metrics"]] == expected

    with get_connection(database) as connection:
        historical = [tuple(row) for row in connection.execute(
            "SELECT fact_type, fact_key, payload_json FROM bemobi_investor_facts ORDER BY id"
        )]
        connection.execute("UPDATE bemobi_quarter_actuals SET notes='newer curated snapshot' WHERE period='2Q26'")
        connection.executescript(MIGRATION.read_text())
        assert [tuple(row) for row in connection.execute(
            "SELECT fact_type, fact_key, payload_json FROM bemobi_investor_facts ORDER BY id"
        )] == historical
        assert connection.execute("SELECT notes FROM bemobi_quarter_actuals WHERE period='2Q26'").fetchone()[0] == "newer curated snapshot"


def test_source_backfill_and_comparison_logic_match_worker():
    assert MIGRATION.read_bytes() == (ROOT / "cloudflare/migrations/0037_bemobi_quarter_actuals.sql").read_bytes()
    assert (ROOT / "backend/app/bemobi/quarter_comparison.py").read_bytes() == (ROOT / "cloudflare/src/bemobi_quarter_comparison.py").read_bytes()


def test_quarter_selection_rolls_over_years_and_uses_company_result_fallback():
    facts = [
        {"period": period, "adjusted_net_revenue_mbrl": 200, "adjusted_ebitda_margin_pct": 30}
        for period in ["4Q25", "1Q25", "3Q25", "1Q26", "2Q26", "invalid"]
    ]
    result = build_quarter_comparison(facts, [], "1Q26")
    assert result["latest_report"]["period"] == "4Q25"
    assert result["prior_year"]["period"] == "1Q25"
    assert result["latest_report"]["metrics"][0]["metric"] == "revenue_mbrl"
    assert build_quarter_comparison(facts, [], "3Q26")["prior_year"]["period"] == "3Q25"
    assert build_quarter_comparison(facts, [], "4Q26")["prior_year"]["period"] == "4Q25"
    assert build_quarter_comparison([], [], "invalid") == {"latest_report": None, "prior_year": None}


@pytest.mark.parametrize("bad", [None, True, "invalid", float("nan"), float("inf")])
def test_invalid_values_and_unadjusted_metrics_are_not_used(bad):
    facts = [{"period": "2Q26", "adjusted_net_income_mbrl": bad, "net_income_mbrl": 40, "revenue_mbrl": 250}]
    row = {"period": "2Q26", "metrics_json": json.dumps([
        {"metric": "revenue_mbrl", "value_mbrl": bad},
        {"metric": "revenue_mbrl", "value_mbrl": 200, "value_pct": 30},
    ])}
    assert build_quarter_comparison(facts, [row], "3Q26")["latest_report"] is None


def test_verified_snapshot_takes_priority_and_zero_is_valid():
    facts = [{"period": "3Q25", "adjusted_net_income_mbrl": 41.0}]
    row = {"period": "3Q25", "source_page": 3, "metrics_json": json.dumps([
        {"metric": "adjusted_net_income_mbrl", "value_mbrl": 42.5},
        {"metric": "capex_mbrl", "value_mbrl": 0},
    ])}
    result = build_quarter_comparison(facts, [row], "3Q26")
    assert result["prior_year"]["metrics"][0]["value_mbrl"] == 42.5
    assert result["prior_year"]["metrics"][1]["value_mbrl"] == 0
    assert result["prior_year"]["source_page"] == 3

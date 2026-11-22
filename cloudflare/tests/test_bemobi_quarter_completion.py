"""Regressions: source-backed CVM quarter rows survive adjusted-result ingest."""
from __future__ import annotations

import asyncio
import json
import sqlite3

from src.bemobi_cvm_financials import _merge_quarter_fact
from src.bemobi_dashboard_base import _distribution_estimate_payload, _valuation_payload
from src.bemobi_web_refresh import _upsert_fact


class Repository:
    def __init__(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE bemobi_investor_facts (
                id INTEGER PRIMARY KEY,
                fact_type TEXT NOT NULL,
                fact_key TEXT NOT NULL,
                as_of_date TEXT,
                published_date TEXT,
                payload_json TEXT NOT NULL,
                source_name TEXT NOT NULL,
                source_url TEXT,
                quality TEXT NOT NULL,
                notes TEXT,
                source_document_id INTEGER,
                updated_at TEXT,
                UNIQUE(fact_type, fact_key)
            );
        """)

    async def first(self, sql, params=()):
        row = self.db.execute(sql, params).fetchone()
        return dict(row) if row is not None else None

    async def run(self, sql, params=()):
        value = self.db.execute(sql, params)
        self.db.commit()
        return value

    def fact(self, key):
        row = self.db.execute(
            "SELECT * FROM bemobi_investor_facts WHERE fact_type='TTM_QUARTER' AND fact_key=?",
            (key,),
        ).fetchone()
        return dict(row) if row is not None else None


def test_new_cvm_quarter_is_created_then_result_kpis_merge_without_erasing_cvm():
    async def scenario():
        repo = Repository()
        cvm = {
            "period": "3Q26",
            "reported_net_income_parent_mbrl": 40.0,
            "reported_net_income_parent_source_url": "https://dados.cvm.gov.br/itr2026.zip",
            "reported_net_debt_mbrl": -250.0,
            "reported_cash_mbrl": 319.0,
            "reported_borrowings_mbrl": 69.0,
        }
        assert await _merge_quarter_fact(repo, cvm) == "inserted"
        original = repo.fact("3Q26")
        assert original["as_of_date"] == "2026-09-30"
        assert original["quality"] == "CVM_OFFICIAL_FINANCIALS_PARTIAL"
        assert json.loads(original["payload_json"])["reported_net_debt_mbrl"] == -250.0

        await _upsert_fact(
            repo, fact_type="TTM_QUARTER", fact_key="3Q26",
            as_of_date="2026-09-30", published_date="2026-11-12",
            payload={
                "period": "3Q26", "adjusted_net_income_mbrl": 51.0,
                "adjusted_ebitda_mbrl": 86.8, "adjusted_cash_generation_mbrl": 70.0,
            }, source_name="BEMOBI_IR", source_url="https://ri.bemobi.com.br/",
            source_document_id=None, quality="OFFICIAL_RESULT_AUTO", notes="fixture",
        )
        merged = json.loads(repo.fact("3Q26")["payload_json"])
        assert merged["adjusted_net_income_mbrl"] == 51.0
        assert merged["reported_net_income_parent_mbrl"] == 40.0
        assert merged["reported_net_debt_mbrl"] == -250.0

        assert await _merge_quarter_fact(
            repo, {**cvm, "reported_net_income_parent_mbrl": 41.0}
        ) == "updated"
        merged = json.loads(repo.fact("3Q26")["payload_json"])
        assert merged["reported_net_income_parent_mbrl"] == 41.0
        assert merged["adjusted_ebitda_mbrl"] == 86.8
        assert await _merge_quarter_fact(repo, {
            **cvm, "reported_net_income_parent_mbrl": 41.0,
        }) == "unchanged"
        assert repo.db.execute("SELECT count(*) FROM bemobi_investor_facts").fetchone()[0] == 1

    asyncio.run(scenario())


def test_full_result_fact_replacement_still_preserves_existing_semantics():
    async def scenario():
        repo = Repository()
        kwargs = dict(
            repo=repo, fact_type="RESULT", fact_key="3Q26",
            as_of_date="2026-09-30", published_date="2026-11-12",
            source_name="CVM", source_url="https://dados.cvm.gov.br/",
            source_document_id=None, quality="OFFICIAL_RESULT_AUTO", notes="fixture",
        )
        await _upsert_fact(
            repo, fact_type="RESULT", fact_key="3Q26",
            as_of_date="2026-09-30", published_date="2026-11-12",
            payload={"period": "3Q26", "cash_mbrl": 2025},
            source_name="CVM", source_url="https://dados.cvm.gov.br/",
            source_document_id=None, quality="OFFICIAL_RESULT_AUTO", notes="fixture",
        )
        await _upsert_fact(
            repo, fact_type="RESULT", fact_key="3Q26",
            as_of_date="2026-09-30", published_date="2026-11-12",
            payload={"period": "3Q26", "cash_mbrl": 319},
            source_name="CVM", source_url="https://dados.cvm.gov.br/",
            source_document_id=None, quality="OFFICIAL_RESULT_AUTO", notes="fixture",
        )
        row = repo.db.execute(
            "SELECT payload_json FROM bemobi_investor_facts WHERE fact_type='RESULT'"
        ).fetchone()
        assert json.loads(row[0]) == {"period": "3Q26", "cash_mbrl": 319}
    asyncio.run(scenario())


def test_incomplete_reported_ttm_explains_missing_quarter_and_suppresses_payout():
    quarters = [
        {"period": p, "adjusted_net_income_mbrl": 35.0,
         "adjusted_ebitda_mbrl": 65.0, "adjusted_cash_generation_mbrl": 50.0,
         "reported_net_income_parent_mbrl": 31.0 if p != "3Q26" else None}
        for p in ("4Q25", "1Q26", "2Q26", "3Q26")
    ]
    valuation = _valuation_payload(
        25.0, {"bemobi_total_shares": 100_000_000}, quarters,
        {"period": "2Q26", "ttm_ebit_mbrl": 150.0, "net_debt_mbrl": -200.0},
    )
    assert valuation["reported_net_income_ttm_mbrl"] is None
    assert valuation["reported_net_income_missing_periods"] == ["3Q26"]
    result = _distribution_estimate_payload(
        valuation=valuation, latest_distribution=None, holding_shares=30_000_000,
        ownership_pct=30.0, brl_nok=1.65, outstanding_otello=70_000_000,
        latest_result_period="3Q26",
    )
    assert result["ready"] is False
    assert result["reason"] == "reported_ttm_not_ready"
    assert result["missing_periods"] == ["3Q26"]


def test_older_ttm_cannot_be_misrepresented_as_current_q3_distribution():
    result = _distribution_estimate_payload(
        valuation={"period": "TTM 3Q25–2Q26", "ttm_end_period": "2Q26",
                   "reported_net_income_ttm_mbrl": 159.7},
        latest_distribution=None, holding_shares=30_000_000,
        ownership_pct=30.0, brl_nok=1.65, outstanding_otello=70_000_000,
        latest_result_period="3Q26",
    )
    assert result["ready"] is False
    assert result["reason"] == "reported_ttm_not_current"
    assert result["missing_periods"] == ["3Q26"]

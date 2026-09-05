from __future__ import annotations

from pathlib import Path

from app.bemobi import consensus as consensus_module
from app.db.connection import get_connection
from app.db.migration_runner import init_database


ROOT = Path(__file__).resolve().parents[2]


def _bemobi_dashboard() -> dict:
    return {
        "ready": True,
        "as_of_date": "2026-08-18",
        "market": {
            "price_brl": 22.8,
            "price_date": "2026-08-18",
            "price_source": "B3",
        },
        "otello": {"bemobi_total_shares": 85_608_392},
    }


def test_bemobi_consensus_builds_targets_broker_multiples_and_beat_miss(tmp_path, monkeypatch) -> None:
    database = str(tmp_path / "bemobi-consensus.db")
    init_database(database)
    monkeypatch.setattr(consensus_module, "bemobi_dashboard", lambda _path=None: _bemobi_dashboard())

    result = consensus_module.bemobi_consensus(database)

    assert result["ready"] is True
    assert result["as_of_date"] == "2026-08-18"

    coverage = result["coverage"]
    assert coverage["analyst_count"] == 4
    assert coverage["buy_count"] == 3
    assert coverage["hold_count"] == 1
    assert coverage["sell_count"] == 0
    assert coverage["buy_pct"] == 75.0
    assert coverage["average_target_brl"] == 30.95
    assert coverage["high_target_brl"] == 35.0
    assert coverage["low_target_brl"] == 24.0
    assert coverage["checked_date"] == "2026-08-19"
    assert abs(coverage["upside_to_average_pct"] - 35.74561403508772) < 1e-12

    analysts = result["analysts"]
    assert [item["institution"] for item in analysts] == ["BTG Pactual", "Itaú BBA", "Morgan Stanley", "XP"]
    assert analysts[-1]["target_price_brl"] == 31.0

    broker = result["broker_estimates"]
    assert broker["source"] == "BTG Pactual"
    assert broker["published_date"] == "2026-05-12"
    assert broker["broker_count"] == 1
    years = broker["years"]
    assert [item["year"] for item in years] == [2026, 2027]
    assert years[0]["revenue_mbrl"] == 814.0
    assert years[0]["ebitda_mbrl"] == 267.0
    assert years[0]["net_income_mbrl"] == 173.0
    assert years[0]["eps_brl"] == 2.1
    assert years[0]["net_debt_mbrl"] == -343.0
    assert years[0]["ev_ebit"] is None
    assert abs(years[0]["market_cap_mbrl"] - 1951.8713376) < 1e-9
    assert abs(years[0]["enterprise_value_mbrl"] - 1608.8713376) < 1e-9
    assert abs(years[0]["pe"] - 11.282493280924855) < 1e-12
    assert abs(years[0]["ev_ebitda"] - 6.02573534681648) < 1e-12
    assert abs(years[0]["earnings_yield_pct"] - 8.863289125025982) < 1e-12

    assert years[1]["revenue_mbrl"] == 916.0
    assert years[1]["ebitda_mbrl"] == 308.0
    assert years[1]["net_income_mbrl"] == 189.0
    assert years[1]["net_debt_mbrl"] == -322.0
    assert abs(years[1]["pe"] - 10.327361574603175) < 1e-12
    assert abs(years[1]["ev_ebitda"] - 5.291790057142857) < 1e-12

    assert result["next_quarter"]["period"] == "3Q26"
    assert result["next_quarter"]["status"] == "WAITING_FOR_PUBLIC_ESTIMATES"
    assert result["next_quarter"]["estimates"] == []

    history = result["beat_miss"]
    assert [item["period"] for item in history] == ["3Q25", "4Q25", "2Q26"]
    assert abs(history[0]["metrics"][0]["beat_miss_pct"] - 2.786885245901649) < 1e-12
    assert abs(history[1]["metrics"][1]["beat_miss_pct"] - 17.307692307692314) < 1e-12
    assert abs(history[2]["metrics"][1]["beat_miss_pct"] - 41.25) < 1e-12


def test_bemobi_consensus_does_not_mix_models_from_different_brokers(tmp_path, monkeypatch) -> None:
    database = str(tmp_path / "bemobi-consensus-brokers.db")
    init_database(database)
    with get_connection(database) as connection:
        connection.execute(
            """
            INSERT INTO bemobi_investor_facts(
                fact_type, fact_key, as_of_date, published_date, payload_json,
                source_name, source_url, quality
            ) VALUES (
                'FORWARD_CONSENSUS', '2028', '2026-08-30', '2026-08-30',
                '{"year": 2028, "revenue_mbrl": 1000}', 'Another Broker',
                'https://example.com/model', 'PUBLIC_BROKER_MODEL'
            )
            """
        )
        connection.commit()
    monkeypatch.setattr(consensus_module, "bemobi_dashboard", lambda _path=None: _bemobi_dashboard())

    broker = consensus_module.bemobi_consensus(database)["broker_estimates"]

    assert broker["source"] == "Another Broker"
    assert broker["year_range"] == "2028E"
    assert [item["year"] for item in broker["years"]] == [2028]


def test_consensus_is_database_backed_and_frontend_prioritizes_investor_questions() -> None:
    backend_app = (ROOT / "backend/app/main.py").read_text(encoding="utf-8")
    worker_app = (ROOT / "cloudflare/src/app.py").read_text(encoding="utf-8")
    worker_service = (ROOT / "cloudflare/src/bemobi_consensus.py").read_text(encoding="utf-8")
    migration = (ROOT / "cloudflare/migrations/0028_replace_aggregator_with_btg_model.sql").read_text(encoding="utf-8")
    frontend = (ROOT / "frontend/src/App.tsx").read_text(encoding="utf-8")
    page = (ROOT / "frontend/src/ConsensusPage.tsx").read_text(encoding="utf-8")
    history_panel = (ROOT / "frontend/src/ConsensusHistoryPanel.tsx").read_text(encoding="utf-8")

    assert '@app.get("/api/bemobi/consensus")' in backend_app
    assert '@app.get("/api/bemobi/consensus")' in worker_app
    assert "load_bemobi_facts" in worker_service
    assert "latest_bemobi_fact" in worker_service
    assert 'load_bemobi_facts(repository, "FORWARD_CONSENSUS")' in worker_service
    assert '"broker_estimates"' in worker_service
    assert "BTG Pactual" in migration
    assert "PUBLIC_BROKER_MODEL" in migration
    assert "lower(source_name) = 'marketscreener'" in migration.lower()
    assert '{ label: "Konsensus", enabled: true }' in frontend
    assert '<ConsensusPage />' in frontend
    assert 'fetch("/api/bemobi/consensus")' in page
    assert "Hva forventer markedet?" in page
    assert "NESTE RAPPORT" in page
    assert "HISTORISK TREFF" in page
    assert "FORWARD ESTIMATER" in page
    assert "Beat/miss per kvartal" in page
    assert "Analytikere og kursmål" in page
    assert "Kilder og metode" in page
    assert "Earnings yield" not in page
    assert "Referansemodell" not in page
    assert "Forward konsensus" not in page
    assert "MarketScreener" not in page
    assert "MarketScreener" not in history_panel
    assert "Siste meglermodell-revisjon" in history_panel
    assert "Forventning → faktisk → revisjon → kursreaksjon" in history_panel
    assert "return null;" not in history_panel
    assert 'nextQuarter?.status === "PUBLIC_ESTIMATES_AVAILABLE"' in page
    assert "nextQuarterEstimates.map" in page
    assert '<span className="pill">KJØP</span>' not in page

from __future__ import annotations

from pathlib import Path

from app.bemobi import consensus as consensus_module


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
        "otello": {
            "bemobi_total_shares": 85_608_392,
        },
    }


def test_bemobi_consensus_builds_targets_forward_multiples_and_beat_miss(monkeypatch) -> None:
    monkeypatch.setattr(consensus_module, "bemobi_dashboard", lambda _path=None: _bemobi_dashboard())

    result = consensus_module.bemobi_consensus("ignored.db")

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
    assert abs(coverage["upside_to_average_pct"] - 35.74561403508772) < 1e-12

    analysts = result["analysts"]
    assert [item["institution"] for item in analysts] == ["BTG Pactual", "Itaú BBA", "Morgan Stanley", "XP"]
    assert analysts[-1]["target_price_brl"] == 31.0

    years = result["forward_consensus"]["years"]
    assert [item["year"] for item in years] == [2026, 2027]
    assert years[0]["revenue_mbrl"] == 814.0
    assert years[0]["ebitda_mbrl"] == 288.2
    assert years[0]["ebit_mbrl"] == 205.4
    assert years[0]["net_income_mbrl"] == 174.3
    assert years[0]["eps_brl"] == 2.07
    assert years[0]["net_debt_mbrl"] == -226.0
    assert abs(years[0]["market_cap_mbrl"] - 1951.8713376) < 1e-9
    assert abs(years[0]["enterprise_value_mbrl"] - 1725.8713376) < 1e-9
    assert abs(years[0]["pe"] - 11.19834387607573) < 1e-12
    assert abs(years[0]["ev_ebitda"] - 5.988450165163082) < 1e-12
    assert abs(years[0]["ev_ebit"] - 8.40248947224927) < 1e-12
    assert abs(years[0]["earnings_yield_pct"] - 8.929891875676468) < 1e-12

    assert years[1]["revenue_mbrl"] == 1002.0
    assert years[1]["ebitda_mbrl"] == 342.5
    assert abs(years[1]["pe"] - 10.187219924843424) < 1e-12
    assert abs(years[1]["ev_ebitda"] - 5.091595146277372) < 1e-12
    assert abs(years[1]["ev_ebit"] - 6.782852343835083) < 1e-12

    assert result["next_quarter"]["period"] == "3Q26"
    assert result["next_quarter"]["status"] == "WAITING_FOR_PUBLIC_ESTIMATES"
    assert result["next_quarter"]["estimates"] == []

    history = result["beat_miss"]
    assert [item["period"] for item in history] == ["3Q25", "4Q25", "2Q26"]
    assert abs(history[0]["metrics"][0]["beat_miss_pct"] - 2.786885245901649) < 1e-12
    assert abs(history[1]["metrics"][1]["beat_miss_pct"] - 17.307692307692314) < 1e-12
    assert abs(history[2]["metrics"][1]["beat_miss_pct"] - 41.25) < 1e-12


def test_consensus_is_exposed_in_backend_worker_and_frontend() -> None:
    backend_app = (ROOT / "backend/app/main.py").read_text(encoding="utf-8")
    worker_app = (ROOT / "cloudflare/src/app.py").read_text(encoding="utf-8")
    worker_service = (ROOT / "cloudflare/src/bemobi_consensus.py").read_text(encoding="utf-8")
    frontend = (ROOT / "frontend/src/App.tsx").read_text(encoding="utf-8")
    page = (ROOT / "frontend/src/ConsensusPage.tsx").read_text(encoding="utf-8")

    assert '@app.get("/api/bemobi/consensus")' in backend_app
    assert '@app.get("/api/bemobi/consensus")' in worker_app
    assert 'ANALYST_COVERAGE' in worker_service
    assert 'FORWARD_CONSENSUS' in worker_service
    assert 'type View = "Oversikt" | "NAV" | "Tilbakekjøp" | "Bemobi" | "Konsensus" | "Aksjonærer";' in frontend
    assert '{ label: "Konsensus", enabled: true }' in frontend
    assert '<ConsensusPage />' in frontend
    assert 'fetch("/api/bemobi/consensus")' in page
    assert "Forward konsensus" in page
    assert "Beat / miss" in page

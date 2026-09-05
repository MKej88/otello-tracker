from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest

from app.bemobi.consensus_history import _market_reaction, build_consensus_history
from app.db.connection import get_connection
from app.db.migration_runner import init_database

ROOT = Path(__file__).resolve().parents[2]


class _FailingRepository:
    async def all(self, *_args, **_kwargs) -> list[dict]:
        raise RuntimeError("databasen er utilgjengelig")


def _beat_miss(period: str = "2Q26") -> list[dict]:
    return [
        {
            "period": period,
            "broker": "XP",
            "published_date": "2026-07-16",
            "source_url": "https://example.test/preview",
            "metrics": [
                {
                    "metric": "adjusted_ebitda_mbrl",
                    "label": "Justert EBITDA",
                    "estimate": 77.0,
                    "actual": 79.4,
                    "beat_miss_pct": (79.4 / 77.0 - 1) * 100,
                }
            ],
        }
    ]


def _seed_bmob3_prices(database: str) -> None:
    with get_connection(database) as connection:
        instrument_id = int(
            connection.execute(
                "SELECT id FROM instruments WHERE symbol='BMOB3'"
            ).fetchone()["id"]
        )
        source_id = int(
            connection.execute("SELECT id FROM sources WHERE code='B3'").fetchone()[
                "id"
            ]
        )
        rows = [
            ("2026-08-11", "20.00"),
            ("2026-08-12", "22.00"),
            ("2026-08-13", "21.00"),
            ("2026-08-14", "23.00"),
            ("2026-08-17", "24.00"),
            ("2026-08-18", "25.00"),
        ]
        for day, price in rows:
            connection.execute(
                """
                INSERT INTO market_prices(
                    instrument_id, observed_at, trading_date, price_type,
                    price, currency, source_id
                ) VALUES (?, ?, ?, 'CLOSE', ?, 'BRL', ?)
                """,
                (instrument_id, f"{day}T20:00:00Z", day, price, source_id),
            )
        connection.commit()


def test_history_links_2q26_beat_miss_to_bmob3_market_reaction(tmp_path) -> None:
    database = str(tmp_path / "consensus-history.db")
    init_database(database)
    _seed_bmob3_prices(database)

    result = build_consensus_history(_beat_miss(), database, current_forward=[])
    event = result["events"][0]

    assert event["period"] == "2Q26"
    assert event["result_date"] == "2026-08-11"
    assert event["expectation"]["broker"] == "XP"
    assert event["expectation"]["metrics"][0]["actual"] == 79.4

    reaction = event["market_reaction"]
    assert reaction["status"] == "OK"
    assert reaction["pre"]["date"] == "2026-08-11"
    assert reaction["day1"]["date"] == "2026-08-12"
    assert reaction["day5"]["date"] == "2026-08-18"
    assert abs(reaction["reaction_1d_pct"] - 10.0) < 1e-12
    assert abs(reaction["reaction_5d_pct"] - 25.0) < 1e-12

    revision = event["model_revision"]
    assert revision["status"] == "WAITING_FOR_PUBLIC_POST_REPORT_MODEL"
    assert revision["target_before_brl"] == 31.0
    assert revision["target_after_brl"] is None
    assert revision["target_revision_pct"] is None


def test_4q25_public_model_revision_keeps_paytime_caveat(tmp_path) -> None:
    database = str(tmp_path / "consensus-history-4q.db")
    init_database(database)
    history = _beat_miss("4Q25")
    history[0]["published_date"] = "2026-02-01"

    result = build_consensus_history(history, database, current_forward=[])
    revision = result["events"][0]["model_revision"]

    assert revision["status"] == "PUBLIC_UPDATE"
    assert revision["target_before_brl"] == 30.5
    assert revision["target_after_brl"] == 31.0
    assert abs(revision["target_revision_pct"] - (31.0 / 30.5 - 1) * 100) < 1e-12
    assert revision["days_after_result"] == 11
    revenue = revision["estimate_revisions"][0]
    assert revenue["before"] == 14.0
    assert revenue["after"] == 26.0
    assert revenue["change_pp"] == 12.0
    assert "Paytime" in revenue["note"]


def test_backend_propagates_price_query_failure() -> None:
    with patch(
        "app.bemobi.consensus_history.get_connection",
        side_effect=RuntimeError("databasen er utilgjengelig"),
    ):
        with pytest.raises(RuntimeError, match="databasen er utilgjengelig"):
            _market_reaction(None, "2026-08-11")


def test_worker_propagates_price_query_failure() -> None:
    module_path = ROOT / "cloudflare/src/bemobi_consensus_history.py"
    spec = importlib.util.spec_from_file_location(
        "worker_consensus_history", module_path
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    with pytest.raises(RuntimeError, match="databasen er utilgjengelig"):
        asyncio.run(module._market_reaction(_FailingRepository(), "2026-08-11"))


def test_history_is_built_and_rendered_on_consensus_page() -> None:
    backend = (ROOT / "backend/app/bemobi/consensus.py").read_text(encoding="utf-8")
    worker = (ROOT / "cloudflare/src/bemobi_consensus.py").read_text(encoding="utf-8")
    worker_history = (ROOT / "cloudflare/src/bemobi_consensus_history.py").read_text(
        encoding="utf-8"
    )
    page = (ROOT / "frontend/src/ConsensusPage.tsx").read_text(encoding="utf-8")
    panel = (ROOT / "frontend/src/ConsensusHistoryPanel.tsx").read_text(
        encoding="utf-8"
    )

    assert '"history_link": build_consensus_history(' in backend
    assert '"history_link": await build_consensus_history(' in worker
    assert "MISSING_PRICE_HISTORY" in worker_history
    assert "ConsensusHistoryPanel" in page
    assert "return null;" not in panel
    assert "Forventning → faktisk → revisjon → kursreaksjon" in panel
    assert "Venter på offentlig modell" in panel
    assert "Siste meglermodell-revisjon" in panel

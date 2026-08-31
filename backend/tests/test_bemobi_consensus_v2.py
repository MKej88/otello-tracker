from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from app.bemobi.consensus_history import build_consensus_history
from app.db.connection import get_connection
from app.db.migration_runner import database_status, init_database


ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
if str(CLOUDFLARE_SRC) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE_SRC))

from bemobi_web_refresh_v2 import _ensure_consensus_event  # noqa: E402


def test_consensus_history_migration_replaces_aggregator_with_broker_baseline(tmp_path) -> None:
    database = str(tmp_path / "consensus-v2.db")
    applied = init_database(database)

    assert "0031" in applied
    status = database_status(database)
    assert status["latest_migration"] == applied[-1]
    assert status["table_counts"]["bemobi_consensus_events"] == 3
    assert status["table_counts"]["bemobi_forward_consensus_snapshots"] == 1

    with get_connection(database) as connection:
        periods = [
            row["period"]
            for row in connection.execute(
                "SELECT period FROM bemobi_consensus_events ORDER BY result_date"
            ).fetchall()
        ]
        baseline = connection.execute(
            "SELECT source_name, observed_date, payload_json FROM bemobi_forward_consensus_snapshots"
        ).fetchone()
        retired = connection.execute(
            "SELECT is_active FROM sources WHERE code='MARKETSCREENER'"
        ).fetchone()
        legacy_facts = connection.execute(
            "SELECT COUNT(*) AS count FROM bemobi_investor_facts WHERE lower(source_name)='marketscreener'"
        ).fetchone()["count"]

    assert periods == ["3Q25", "4Q25", "2Q26"]
    assert baseline["source_name"] == "BTG Pactual"
    assert baseline["observed_date"] == "2026-05-12"
    years = json.loads(baseline["payload_json"])["years"]
    assert [item["year"] for item in years] == [2026, 2027]
    assert years[0]["ebitda_mbrl"] == 267.0
    assert years[1]["revenue_mbrl"] == 916.0
    assert retired is None or retired["is_active"] == 0
    assert legacy_facts == 0


def test_forward_revision_tracker_compares_last_two_same_broker_snapshots(tmp_path) -> None:
    database = str(tmp_path / "consensus-revisions.db")
    init_database(database)
    second_payload = {
        "years": [
            {
                "year": 2026,
                "revenue_mbrl": 814.0,
                "ebitda_mbrl": 280.0,
                "net_income_mbrl": 173.0,
                "eps_brl": 2.10,
                "net_debt_mbrl": -343.0,
            },
            {
                "year": 2027,
                "revenue_mbrl": 916.0,
                "ebitda_mbrl": 308.0,
                "net_income_mbrl": 189.0,
                "eps_brl": 2.20,
                "net_debt_mbrl": -322.0,
            },
        ]
    }
    with get_connection(database) as connection:
        connection.execute(
            """
            INSERT INTO bemobi_forward_consensus_snapshots(
                source_name, observed_date, payload_json, content_hash,
                source_url, quality
            ) VALUES ('BTG Pactual','2026-08-20',?,'changed','https://example.test','TEST')
            """,
            (json.dumps(second_payload, sort_keys=True, separators=(",", ":")),),
        )
        connection.commit()

    history = build_consensus_history([], database, current_forward=[])
    tracker = history["forward_revision_tracker"]
    assert tracker["comparison_ready"] is True
    assert tracker["same_source_snapshots"] == 2
    assert tracker["baseline_date"] == "2026-05-12"
    assert tracker["latest_date"] == "2026-08-20"
    changes = tracker["latest_changes"]
    assert len(changes) == 1
    assert changes[0]["year"] == 2026
    assert changes[0]["metric"] == "ebitda_mbrl"
    assert changes[0]["before"] == 267.0
    assert changes[0]["after"] == 280.0


def test_history_metadata_is_not_hardcoded_in_python_anymore() -> None:
    backend = (ROOT / "backend/app/bemobi/consensus_history.py").read_text(encoding="utf-8")
    worker = (ROOT / "cloudflare/src/bemobi_consensus_history.py").read_text(encoding="utf-8")
    assert "EVENT_METADATA" not in backend
    assert "EVENT_METADATA" not in worker
    assert "FROM bemobi_consensus_events" in backend
    assert "FROM bemobi_consensus_events" in worker


class _EventRepository:
    def __init__(self) -> None:
        self.inserted: list[tuple] = []

    async def first(self, sql: str, parameters=()):
        if "FROM bemobi_consensus_events" in sql:
            return None
        if "FROM bemobi_investor_facts" in sql:
            return {
                "published_date": "2026-11-10",
                "source_name": "CVM",
                "source_url": "https://example.test/3q26.pdf",
                "source_document_id": 55,
            }
        raise AssertionError(sql)

    async def run(self, sql: str, parameters=()):
        assert "INSERT INTO bemobi_consensus_events" in sql
        self.inserted.append(tuple(parameters))


def test_new_result_creates_waiting_history_event_without_inventing_broker_values() -> None:
    repository = _EventRepository()
    written = asyncio.run(
        _ensure_consensus_event(
            repository,
            result_refresh={"status": "ok", "period": "3Q26"},
            target_date="2026-11-10",
        )
    )
    assert written == 1
    assert len(repository.inserted) == 1
    values = repository.inserted[0]
    assert values[0] == "3Q26"
    model = json.loads(values[4])
    assert model["status"] == "WAITING_FOR_PUBLIC_POST_REPORT_MODEL"
    assert model["target_before_brl"] is None
    assert model["target_after_brl"] is None


def test_full_workflow_routes_through_canonical_runtime_refresh() -> None:
    entry = (ROOT / "cloudflare/src/entry.py").read_text(encoding="utf-8")
    assert "from bemobi_web_refresh_runtime import refresh_bemobi_web" in entry

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

from bemobi_web_refresh_v2 import (  # noqa: E402
    _ensure_consensus_event,
    parse_forward_consensus_html,
)


def _forward_html() -> str:
    return """
    <table>
      <tr><th></th><th>2026</th><th>2027</th><th>2028</th></tr>
      <tr><td>Net sales</td><td>814</td><td>1,002</td><td>1,180</td></tr>
      <tr><td>EBITDA</td><td>288.2</td><td>342.5</td><td>401.0</td></tr>
      <tr><td>EBIT</td><td>205.4</td><td>257.1</td><td>306.0</td></tr>
      <tr><td>Net income</td><td>174.3</td><td>191.6</td><td>224.0</td></tr>
      <tr><td>EPS</td><td>2.07</td><td>2.16</td><td>2.55</td></tr>
      <tr><td>Net debt</td><td>-226</td><td>-208</td><td>-180</td></tr>
    </table>
    """


def test_forward_parser_rolls_calendar_without_hardcoded_2026_2027() -> None:
    years = parse_forward_consensus_html(_forward_html(), as_of_year=2027)
    assert [item["year"] for item in years] == [2027, 2028]
    assert years[0]["revenue_mbrl"] == 1002.0
    assert years[1]["ebitda_mbrl"] == 401.0


def test_consensus_history_migration_seeds_data_backed_baseline(tmp_path) -> None:
    database = str(tmp_path / "consensus-v2.db")
    applied = init_database(database)

    assert "0022" in applied
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

    assert periods == ["3Q25", "4Q25", "2Q26"]
    assert baseline["source_name"] == "MarketScreener"
    assert baseline["observed_date"] == "2026-08-19"
    assert [item["year"] for item in json.loads(baseline["payload_json"])["years"]] == [2026, 2027]


def test_forward_revision_tracker_compares_last_two_same_source_snapshots(tmp_path) -> None:
    database = str(tmp_path / "consensus-revisions.db")
    init_database(database)
    second_payload = {
        "years": [
            {
                "year": 2026,
                "revenue_mbrl": 814.0,
                "ebitda_mbrl": 300.0,
                "ebit_mbrl": 205.4,
                "net_income_mbrl": 174.3,
                "eps_brl": 2.07,
                "net_debt_mbrl": -226.0,
            },
            {
                "year": 2027,
                "revenue_mbrl": 1002.0,
                "ebitda_mbrl": 342.5,
                "ebit_mbrl": 257.1,
                "net_income_mbrl": 191.6,
                "eps_brl": 2.16,
                "net_debt_mbrl": -208.0,
            },
        ]
    }
    with get_connection(database) as connection:
        connection.execute(
            """
            INSERT INTO bemobi_forward_consensus_snapshots(
                source_name, observed_date, payload_json, content_hash,
                source_url, quality
            ) VALUES ('MarketScreener','2026-08-20',?,'changed','https://example.test','TEST')
            """,
            (json.dumps(second_payload, sort_keys=True, separators=(",", ":")),),
        )
        connection.commit()

    history = build_consensus_history([], database, current_forward=[])
    tracker = history["forward_revision_tracker"]
    assert tracker["comparison_ready"] is True
    assert tracker["same_source_snapshots"] == 2
    assert tracker["baseline_date"] == "2026-08-19"
    assert tracker["latest_date"] == "2026-08-20"
    changes = tracker["latest_changes"]
    assert len(changes) == 1
    assert changes[0]["year"] == 2026
    assert changes[0]["metric"] == "ebitda_mbrl"
    assert changes[0]["before"] == 288.2
    assert changes[0]["after"] == 300.0


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

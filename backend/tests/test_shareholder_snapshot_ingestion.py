from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
if str(CLOUDFLARE_SRC) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE_SRC))

from shareholder_snapshot_ingestion import (  # noqa: E402
    EXPECTED_ROWS,
    canonical_rows,
    parse_rendered_html,
    parse_scrape_payload,
    validate_rows,
)


def _row_html(rank: int) -> str:
    shares = 4_000_000 - rank * 100_000
    return (
        f"<td>{rank}</td>"
        f"<td>Investor {rank} AS</td>"
        f"<td>NO</td>"
        f"<td>{shares:,}</td>"
        f"<td>{4 - rank * 0.1:.2f}%</td>"
        f"<td>Ordinary</td>"
    )


def test_scrape_payload_parses_exact_top20() -> None:
    payload = {
        "success": True,
        "result": [
            {
                "selector": "table tbody tr",
                "results": [
                    {"html": _row_html(rank), "text": ""}
                    for rank in range(1, EXPECTED_ROWS + 1)
                ],
            }
        ],
    }

    rows = parse_scrape_payload(payload)
    validate_rows(rows, total_issued_shares=73_790_829)

    assert len(rows) == 20
    assert rows[0] == {
        "rank": 1,
        "shareholder_name": "Investor 1 AS",
        "country": "NO",
        "shares": 3_900_000,
        "ownership_pct": "3.9",
        "account_type": "Ordinary",
    }
    assert rows[-1]["rank"] == 20
    assert rows[-1]["shares"] == 2_000_000


def test_rendered_html_fallback_parses_rows() -> None:
    html = "<table><tbody>" + "".join(
        f"<tr>{_row_html(rank)}</tr>" for rank in range(1, EXPECTED_ROWS + 1)
    ) + "</tbody></table>"
    rows = parse_rendered_html(html)
    assert [row["rank"] for row in rows] == list(range(1, 21))


def test_validation_rejects_partial_or_duplicate_snapshot() -> None:
    rows = [
        {
            "rank": rank,
            "shareholder_name": f"Investor {rank}",
            "country": "NO",
            "shares": 100_000,
            "ownership_pct": "0.1",
            "account_type": None,
        }
        for rank in range(1, 20)
    ]
    with pytest.raises(ValueError, match="Forventet 20"):
        validate_rows(rows, total_issued_shares=73_790_829)

    rows.append({**rows[-1], "rank": 20})
    with pytest.raises(ValueError, match="duplisert"):
        validate_rows(rows, total_issued_shares=73_790_829)


def test_canonical_rows_are_stable_and_semantic() -> None:
    rows = [
        {
            "rank": rank,
            "shareholder_name": f" Investor {rank}  AS ",
            "country": "NO",
            "shares": 1_000_000 - rank,
            "ownership_pct": "1.2",
            "account_type": None,
        }
        for rank in range(1, 21)
    ]
    first = canonical_rows(rows)
    second = canonical_rows(rows)
    assert first == second
    decoded = json.loads(first)
    assert decoded[0]["shareholder_name"] == "Investor 1 AS"


def test_worker_config_has_weekly_browser_run_workflow() -> None:
    config = json.loads((ROOT / "cloudflare/wrangler.jsonc").read_text(encoding="utf-8"))
    worker = (ROOT / "cloudflare/src/worker.py").read_text(encoding="utf-8")
    workflow = (ROOT / "cloudflare/src/shareholder_snapshot_workflow.py").read_text(encoding="utf-8")
    ingestion = (ROOT / "cloudflare/src/shareholder_snapshot_ingestion.py").read_text(encoding="utf-8")

    assert config["main"] == "src/worker.py"
    assert config["browser"]["binding"] == "BROWSER"
    assert config["browser"]["remote"] is True
    shareholder_workflow = next(
        item for item in config["workflows"] if item["binding"] == "SHAREHOLDER_SNAPSHOT"
    )
    assert shareholder_workflow["class_name"] == "ShareholderSnapshotWorkflow"
    assert shareholder_workflow["schedules"] == ["15 7 * * 6"]
    assert "ShareholderSnapshotWorkflow" in worker
    assert "refresh_shareholder_snapshot" in workflow
    assert 'quickAction(\n        "scrape"' in ingestion
    assert "EXPECTED_ROWS = 20" in ingestion
    assert "MAX_BROWSER_CALLS = 2" in ingestion

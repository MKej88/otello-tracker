from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE = ROOT / "cloudflare"
if str(CLOUDFLARE) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE))

from src.otello_interest_income import (  # noqa: E402
    ATTRIBUTION_POLICY,
    INTEREST_PARSER_VERSION,
    parse_report_interest_income,
    sync_interest_income_anchors_from_report_result,
)


FIRST_HALF_2026_INTEREST = """
OTELLO CORPORATION ASA
FIRST-HALF REPORT
Consolidated statement of cash flows
Note 1H 2026 1H 2025 YTD 2026 YTD 2025
(USD thousands)
Interest income received 326 537 326 537

The key FX rates used during the half were:
USD:BRL
For the June period 2026: 5.4000
For the March period 2026: 5.5000
USD:NOK
As of June 30, 2026: 9.5000
For the June period 2026: 9.5815
For the March period 2026: 9.6605
"""


SECOND_HALF_2026_INTEREST = """
OTELLO CORPORATION ASA
SECOND-HALF REPORT
Consolidated statement of cash flows
(USD thousands)
Interest income received
412 339 738 665

The key FX rates used during the half were:
USD:BRL
For the December period 2026: 5.2500
For the September period 2026: 5.3500
USD:NOK
For the December period 2026: 9.8123
For the September period 2026: 9.9345
"""


def test_interest_parser_extracts_cash_interest_and_only_usd_nok_rates() -> None:
    parsed = parse_report_interest_income(FIRST_HALF_2026_INTEREST, "1H26")

    assert parsed["valid"] is True, parsed["issues"]
    assert parsed["parser_version"] == INTEREST_PARSER_VERSION
    facts = parsed["facts"]
    assert facts["source_period_start"] == "2026-01-01"
    assert facts["source_period_end"] == "2026-06-30"
    assert facts["period_days"] == 181
    assert facts["amount_usd"] == "326000"
    assert facts["fx_segments"] == [
        {
            "start_date": "2026-01-01",
            "end_date": "2026-03-31",
            "usd_nok": "9.6605",
            "source_label": "For the March period 2026",
        },
        {
            "start_date": "2026-04-01",
            "end_date": "2026-06-30",
            "usd_nok": "9.5815",
            "source_label": "For the June period 2026",
        },
    ]


def test_interest_parser_supports_second_half_and_wrapped_cash_flow_value() -> None:
    parsed = parse_report_interest_income(SECOND_HALF_2026_INTEREST, "2H26")

    assert parsed["valid"] is True, parsed["issues"]
    facts = parsed["facts"]
    assert facts["period_days"] == 184
    assert facts["amount_usd"] == "412000"
    assert [segment["usd_nok"] for segment in facts["fx_segments"]] == ["9.9345", "9.8123"]


def test_interest_parser_fails_closed_if_report_fx_table_drifts() -> None:
    broken = FIRST_HALF_2026_INTEREST.replace("For the June period 2026: 9.5815\n", "")
    parsed = parse_report_interest_income(broken, "1H26")

    assert parsed["valid"] is False
    assert "missing_usd_nok_june_2026" in parsed["issues"]


class _Repository:
    def __init__(self) -> None:
        self.created: list[dict] = []

    async def all(self, sql, parameters=()):
        assert "ECONOMIC_NAV_INTEREST_INCOME_ANCHOR" in sql
        return []

    async def first(self, sql, parameters=()):
        assert "FROM source_documents WHERE id=?" in sql
        assert parameters == (77,)
        return {
            "external_id": "newsweb-report:12345:67890",
            "url": "https://newsweb.oslobors.no/report.pdf",
        }

    async def create_source_document(self, **kwargs):
        self.created.append(kwargs)
        return 88


def test_new_auto_applied_report_creates_idempotent_interest_anchor_input() -> None:
    repository = _Repository()
    report_result = {
        "results": [
            {
                "status": "applied",
                "report_document_id": 77,
                "facts": {"source_period": "2H26"},
            }
        ]
    }

    async def loader(message_id: int, attachment_id: int) -> str:
        assert (message_id, attachment_id) == (12345, 67890)
        return SECOND_HALF_2026_INTEREST

    result = asyncio.run(
        sync_interest_income_anchors_from_report_result(
            repository,
            report_result,
            report_text_loader=loader,
        )
    )

    assert result["status"] == "ok"
    assert result["written"] == 1
    assert len(repository.created) == 1
    created = repository.created[0]
    assert created["external_id"] == "economic-nav-interest:2H26"
    assert created["document_type"] == "ECONOMIC_NAV_INTEREST_INCOME_ANCHOR"
    metadata = created["metadata"]
    assert metadata["amount_usd"] == "412000"
    assert metadata["source_period_start"] == "2026-07-01"
    assert metadata["source_period_end"] == "2026-12-31"
    assert metadata["auto_extracted"] is True
    assert metadata["attribution_policy"] == ATTRIBUTION_POLICY
    assert json.loads(json.dumps(metadata))["fx_segments"][0]["usd_nok"] == "9.9345"


def test_scheduled_pipeline_runs_interest_sync_after_report_ingestion() -> None:
    scheduled = (ROOT / "cloudflare" / "src" / "scheduled.py").read_text(encoding="utf-8")
    assert "sync_interest_income_anchors_from_report_result" in scheduled
    assert '"otello_interest"' in scheduled
    assert "automatic_interest_income_ingestion" in scheduled

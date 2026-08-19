from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE = ROOT / "cloudflare"
if str(CLOUDFLARE) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE))

from src.otello_report_ingestion import (  # noqa: E402
    REPORT_PARSER_VERSION,
    parse_otello_financial_report,
)


FIRST_HALF_2025 = """
OTELLO CORPORATION ASA
FIRST-HALF REPORT
Consolidated statement of financial position
USD thousands
06/30/2025 12/31/2024
Investments 6 118,325 117,000
Other noncurrent assets 650 600
Other receivables 223 200
Cash and cash equivalents 4 14,694 13,500
Total assets 133,893 131,300
Total equity 132,194 129,400
Total liabilities 1,699 1,900

Consolidated statement of profit or loss
USD thousands
Employee benefits expense (643) (610)
Other operating expenses (643) (620)

Note 6 Investments
Investments in Bemobi Mobile Tech S.A (associate) 117,505 116,000
Other shares 820 1,000
"""


SECOND_HALF_2025 = """
OTELLO CORPORATION ASA
SECOND-HALF REPORT
Consolidated statement of financial position
USD thousands
12/31/2025 06/30/2025
Investments 5 115,552 118,325
Other receivables 768 223
Cash and cash equivalents 6 15,881 14,694
Total assets 132,202 133,893
Total equity 126,083 132,194
Options liabilities 4 4,408 -
Total liabilities 6,119 1,699

Consolidated statement of profit or loss
USD thousands
Employee benefits expense (5,023) (643)
Other operating expenses (425) (643)

Alternative performance measures
Stock-based compensation expenses 4,427 -

Note 5 Investments
Investments in Bemobi Mobile Tech S.A (associate) 114,732 117,505
Other shares 821 820
"""


def test_first_half_2025_layout_parses_known_report_anchors() -> None:
    result = parse_otello_financial_report(FIRST_HALF_2025)
    assert result["valid"] is True, result["issues"]
    assert result["parser_version"] == REPORT_PARSER_VERSION
    facts = result["facts"]

    assert facts["report_date"].isoformat() == "2025-06-30"
    assert facts["report_kind"] == "1H"
    assert facts["source_period"] == "1H25"
    assert facts["period_days"] == 181
    assert facts["cash_usd"] == Decimal("14694000")
    assert facts["total_assets_usd"] == Decimal("133893000")
    assert facts["total_liabilities_usd"] == Decimal("1699000")
    assert facts["bemobi_carrying_usd"] == Decimal("117505000")
    assert facts["option_liability_usd"] == Decimal("0")
    assert facts["other_net_assets_usd"] == Decimal("-5000")
    assert facts["employee_benefits_usd"] == Decimal("643000")
    assert facts["other_operating_expenses_usd"] == Decimal("643000")
    assert facts["stock_compensation_usd"] == Decimal("0")
    assert facts["recurring_opex_usd"] == Decimal("1286000")


def test_second_half_2025_layout_parses_option_and_recurring_costs() -> None:
    result = parse_otello_financial_report(SECOND_HALF_2025)
    assert result["valid"] is True, result["issues"]
    facts = result["facts"]

    assert facts["report_date"].isoformat() == "2025-12-31"
    assert facts["report_kind"] == "2H"
    assert facts["source_period"] == "2H25"
    assert facts["period_days"] == 184
    assert facts["cash_usd"] == Decimal("15881000")
    assert facts["total_assets_usd"] == Decimal("132202000")
    assert facts["total_liabilities_usd"] == Decimal("6119000")
    assert facts["bemobi_carrying_usd"] == Decimal("114732000")
    assert facts["option_liability_usd"] == Decimal("4408000")
    assert facts["other_net_assets_usd"] == Decimal("-4530000")
    assert facts["employee_benefits_usd"] == Decimal("5023000")
    assert facts["stock_compensation_usd"] == Decimal("4427000")
    assert facts["other_operating_expenses_usd"] == Decimal("425000")
    assert facts["recurring_opex_usd"] == Decimal("1021000")


def test_report_parser_fails_closed_when_balance_sheet_does_not_reconcile() -> None:
    broken = FIRST_HALF_2025.replace("Total equity 132,194", "Total equity 120,000")
    result = parse_otello_financial_report(broken)
    assert result["valid"] is False
    assert any(issue.startswith("balance_sheet_not_balanced:") for issue in result["issues"])


def test_post_grant_report_requires_option_liability_and_stock_compensation() -> None:
    report = SECOND_HALF_2025.replace("Options liabilities 4 4,408 -\n", "").replace(
        "Stock-based compensation expenses 4,427 -\n", ""
    )
    result = parse_otello_financial_report(report)
    assert result["valid"] is False
    assert "missing_option_liability_post_grant" in result["issues"]
    assert "missing_stock_compensation_post_grant" in result["issues"]


def test_worker_wiring_keeps_report_ingestion_zero_touch_and_fail_closed() -> None:
    scheduled = (ROOT / "cloudflare" / "src" / "scheduled.py").read_text(encoding="utf-8")
    entry = (ROOT / "cloudflare" / "src" / "entry.py").read_text(encoding="utf-8")
    full_refresh = (ROOT / "cloudflare" / "src" / "full_refresh.py").read_text(encoding="utf-8")
    newsweb = (ROOT / "cloudflare" / "src" / "newsweb_ingestion.py").read_text(encoding="utf-8")
    option_model = (ROOT / "cloudflare" / "src" / "option_liability.py").read_text(encoding="utf-8")
    report_ingestion = (ROOT / "cloudflare" / "src" / "otello_report_ingestion.py").read_text(
        encoding="utf-8"
    )

    assert 'PHASE = "16.1"' in scheduled
    assert "process_pending_otello_reports" in scheduled
    assert "archive_bucket=bindings.SOURCE_ARCHIVE" in entry
    assert '"ingest Otello financial reports"' in entry
    assert '"otello_reports": "NEWSWEB"' in full_refresh
    assert "STRICT_VALIDATION_FAIL_CLOSED" in report_ingestion
    assert "auto_apply_status" in report_ingestion
    assert "company_news.processing_status IN ('APPLIED','IGNORED','REVIEW_REQUIRED')" in newsweb
    assert '"first-half report"' in newsweb
    assert '"second-half report"' in newsweb
    assert "document_type='OTELLO_FINANCIAL_REPORT'" in option_model
    assert 'metadata.get("auto_apply_status") != "APPLIED"' in option_model

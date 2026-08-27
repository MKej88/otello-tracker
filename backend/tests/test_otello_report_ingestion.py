from __future__ import annotations

import asyncio
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE = ROOT / "cloudflare"
if str(CLOUDFLARE) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE))

from src.otello_report_ingestion import (  # noqa: E402
    REPORT_PARSER_VERSION,
    _prepare_post_report_cash_events,
    _upsert_ona_anchor,
    _upsert_post_report_cash_events,
    parse_otello_financial_report,
)


# Mirrors the relevant extracted table shapes from Otello's published 1H25 report.
# The balance sheet has three date columns, while the income statement has current,
# comparison and YTD columns. This is deliberately not simplified to a two-column fixture.
FIRST_HALF_2025 = """
OTELLO CORPORATION ASA
FIRST-HALF REPORT

Consolidated statement of comprehensive income
Note 1H 2025 1H 2024 % YTD 2025 YTD 2024 %
USD thousands, except per share amounts
Employee benefits expense (643) (937) -31 % (643) (937) -31 %
Other operating expenses (643) (678) -5 % (643) (678) -5 %

Consolidated statement of financial position
Note 06/30/2025 06/30/2024 12/31/2024
(USD thousands) (Audited)
Investments 6 118,325 80,773 69,698
Other non-current assets 650 - -
Other receivables 223 236 136
Cash and cash equivalents 14,694 14,518 10,454
Total assets 133,893 95,590 80,288
Total equity 132,194 94,943 78,957
Total liabilities 1,699 647 1,330

Note 6 - Investments
Investments in Bemobi Mobile Tech S.A (associate) 117,505 79,996
Other shares 820 777
"""


# Mirrors the relevant extracted table shapes from Otello's published 2H25 report.
# The P&L has four amount columns, while the balance sheet has two dates.
SECOND_HALF_2025 = """
OTELLO CORPORATION ASA
SECOND-HALF REPORT

Consolidated statement of comprehensive income
Note 2H 2025 2H 2024 % YTD 2025 YTD 2024 %
USD thousands, except per share amounts
Employee benefits expense (5,023) (1,337) 276 % (5,666) (2,273) 149 %
Other operating expenses (425) (479) -11 % (1,069) (1,157) -8 %

Consolidated statement of financial position
Note 12/31/2025 12/31/2024
(USD thousands)
Investments 5 115,552 69,698
Other receivables 768 136
Cash and cash equivalents 15,881 10,454
Total assets 132,202 80,288
Total equity 126,083 78,957
Options liabilities 4,408 -
Total liabilities 6,119 1,330

Alternative performance measures
Stock-based compensation expenses 4,427 - 4,427 -

Note 5 - Investments
Investments in Bemobi Mobile Tech S.A (associate) 114,732 68,877
Other shares 820 821
"""


# Mirrors pypdf extraction from Otello's published 1H26 report. In this report both
# Employee benefits and Options liabilities have an explicit Note column before the
# current-period amount. It also discloses a confirmed post-balance-sheet patent receipt.
FIRST_HALF_2026 = """
FIRST-HALF REPORT
OTELLO CORPORATION ASA

Consolidated statement of comprehensive income
Note 1H 2026 1H 2025 % YTD 2026 YTD 2025 %
USD thousands, except per share amounts
Employee benefits expense 6 (1,105) (643) 72 % (1,105) (643) 72 %
Other operating expenses (786) (643) 22 % (786) (643) 22 %

Consolidated statement of financial position
Note 06/30/2026 06/30/2025 12/31/2025
(USD thousands) (Audited)
Assets
Investments 5, 9 122,233 121,777 117,895
Other non-current assets - 650 -
Total non-current assets 122,233 122,427 117,895
Other receivables 892 223 768
Cash and cash equivalents 10,632 14,694 15,881
Total current assets 11,524 14,918 16,649
Total assets 133,757 137,345 134,544
Shareholders' equity and liabilities
Equity attributable to owners of the company 9 131,139 135,646 132,460
Total equity 131,139 135,646 132,460
Liabilities
Other non-current liabilities 1,409 1,166 1,298
Options liabilities 6 722 - 314
Total non-current liabilities 2,131 1,166 1,612
Accounts payable 129 24 43
Other current liabilities 358 508 430
Total current liabilities 487 533 473
Total liabilities 2,617 1,699 2,085

Consolidated statement of cash flows
Note 1H 2026 1H 2025 YTD 2026 YTD 2025
(USD thousands)

Note 5 - Investments
Investments in Bemobi Mobile Tech S.A (associate) 118,297 120,958
Investments in other shares 3,936 819

Alternative performance measures
Stock-based compensation expenses 418 - 418 -

Events after the end of the half
On July 22, 2026, Otello received the final
instalment from the sale of patents from
2025, being a net amount of USD 650
thousand.
"""


def test_first_half_2025_real_layout_uses_current_not_comparison_column() -> None:
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
    assert facts["other_shares_investment_usd"] == Decimal("820000")
    assert facts["option_liability_usd"] == Decimal("0")
    assert facts["other_net_assets_usd"] == Decimal("-5000")
    assert facts["employee_benefits_usd"] == Decimal("643000")
    assert facts["other_operating_expenses_usd"] == Decimal("643000")
    assert facts["stock_compensation_usd"] == Decimal("0")
    assert facts["recurring_opex_usd"] == Decimal("1286000")
    assert facts["post_report_cash_events"] == []

    # Explicit guards against accidentally selecting 1H24 / 12M24 comparison values.
    assert facts["cash_usd"] != Decimal("14518000")
    assert facts["cash_usd"] != Decimal("10454000")
    assert facts["total_assets_usd"] != Decimal("95590000")


def test_second_half_2025_real_layout_uses_2h_not_ytd_column() -> None:
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
    assert facts["other_shares_investment_usd"] == Decimal("820000")
    assert facts["option_liability_usd"] == Decimal("4408000")
    assert facts["other_net_assets_usd"] == Decimal("-4530000")
    assert facts["employee_benefits_usd"] == Decimal("5023000")
    assert facts["stock_compensation_usd"] == Decimal("4427000")
    assert facts["other_operating_expenses_usd"] == Decimal("425000")
    assert facts["recurring_opex_usd"] == Decimal("1021000")
    assert facts["post_report_cash_events"] == []

    # The YTD employee-benefit figure is 5,666; the recurring 2H input must use 5,023.
    assert facts["employee_benefits_usd"] != Decimal("5666000")


def test_first_half_2026_real_layout_skips_note_column_and_extracts_patent_receipt() -> None:
    result = parse_otello_financial_report(FIRST_HALF_2026)
    assert result["valid"] is True, result["issues"]
    assert result["parser_version"] == "otello-financial-report-v4"
    facts = result["facts"]

    assert facts["report_date"].isoformat() == "2026-06-30"
    assert facts["report_kind"] == "1H"
    assert facts["source_period"] == "1H26"
    assert facts["period_days"] == 181
    assert facts["cash_usd"] == Decimal("10632000")
    assert facts["total_assets_usd"] == Decimal("133757000")
    assert facts["total_equity_usd"] == Decimal("131139000")
    assert facts["total_liabilities_usd"] == Decimal("2617000")
    assert facts["bemobi_carrying_usd"] == Decimal("118297000")
    assert facts["other_shares_investment_usd"] == Decimal("3936000")
    assert facts["option_liability_usd"] == Decimal("722000")
    assert facts["other_net_assets_usd"] == Decimal("2211000")
    assert facts["employee_benefits_usd"] == Decimal("1105000")
    assert facts["other_operating_expenses_usd"] == Decimal("786000")
    assert facts["stock_compensation_usd"] == Decimal("418000")
    assert facts["recurring_opex_usd"] == Decimal("1473000")

    # Regression guards: 6 is the Note reference, not a USD-thousand current-period value.
    assert facts["employee_benefits_usd"] != Decimal("6000")
    assert facts["option_liability_usd"] != Decimal("6000")

    assert facts["post_report_cash_events"] == [
        {
            "event_type": "PATENT_SALE_FINAL_INSTALMENT",
            "movement_date": __import__("datetime").date(2026, 7, 22),
            "amount_usd": Decimal("650000"),
            "description": "Final net instalment from the 2025 patent sale",
        }
    ]


def test_report_parser_fails_closed_without_other_shares_investment() -> None:
    broken = FIRST_HALF_2026.replace("Investments in other shares 3,936 819\n", "")
    result = parse_otello_financial_report(broken)
    assert result["valid"] is False
    assert "missing_other_shares_investment" in result["issues"]


class _PostReportCashRepository:
    def __init__(self) -> None:
        self.movement = None
        self.insert_count = 0

    async def first(self, sql, parameters=()):
        if "FROM fx_rates" in sql:
            assert parameters[0] == "2026-07-22"
            return {
                "id": 71,
                "rate_date": "2026-07-22",
                "rate": "10",
                "source_document_id": 17,
            }
        if "FROM cash_movements WHERE external_movement_id" in sql:
            return dict(self.movement) if self.movement is not None else None
        raise AssertionError(sql)

    async def run(self, sql, parameters=()):
        assert "INSERT INTO cash_movements" in sql
        (
            movement_date,
            amount_nok,
            amount_original,
            fx_rate,
            description,
            source_document_id,
            external_movement_id,
        ) = parameters
        self.insert_count += 1
        self.movement = {
            "id": 72,
            "movement_date": movement_date,
            "amount_nok": amount_nok,
            "amount_original": amount_original,
            "currency": "USD",
            "fx_rate_to_nok": fx_rate,
            "description": description,
            "source_document_id": source_document_id,
            "external_movement_id": external_movement_id,
        }
        return None


def test_first_half_2026_patent_receipt_is_idempotent_confirmed_cash_movement() -> None:
    facts = parse_otello_financial_report(FIRST_HALF_2026)["facts"]
    repository = _PostReportCashRepository()
    prepared = asyncio.run(_prepare_post_report_cash_events(repository, facts))
    assert len(prepared) == 1
    assert prepared[0]["amount_nok"] == Decimal("6500000")

    first = asyncio.run(_upsert_post_report_cash_events(repository, 99, prepared))
    assert first["status"] == "ok"
    assert first["count"] == 1
    assert first["events"][0]["status"] == "inserted"
    assert repository.insert_count == 1
    assert repository.movement["amount_original"] == "650000"
    assert repository.movement["amount_nok"] == "6500000"
    assert repository.movement["fx_rate_to_nok"] == "10"
    assert repository.movement["source_document_id"] == 99
    assert repository.movement["external_movement_id"] == (
        "otello-report-post-cash:PATENT_SALE_FINAL_INSTALMENT:2026-07-22"
    )

    second = asyncio.run(_upsert_post_report_cash_events(repository, 99, prepared))
    assert second["events"][0]["status"] == "existing"
    assert repository.insert_count == 1


class _OnaRepository:
    def __init__(self) -> None:
        self.report_insert = None
        self.converted_written = False

    async def run(self, sql, parameters=()):
        if "INSERT INTO other_net_assets_reported_anchors" in sql:
            self.report_insert = (sql, tuple(parameters))
            return None
        if "INSERT INTO other_net_assets_anchors" in sql:
            self.converted_written = True
            return None
        raise AssertionError(sql)

    async def first(self, sql, parameters=()):
        if "SELECT id FROM other_net_assets_reported_anchors" in sql:
            return {"id": 7}
        if "SELECT id FROM other_net_assets_anchors WHERE reported_anchor_id" in sql:
            return {"id": 8} if self.converted_written else None
        raise AssertionError(sql)


def test_ona_anchor_persists_other_shares_investment_from_parser() -> None:
    facts = parse_otello_financial_report(FIRST_HALF_2026)["facts"]
    repository = _OnaRepository()
    fx = {"id": 3, "rate": "10", "rate_date": "2026-06-30"}

    reported_id, converted_id = asyncio.run(_upsert_ona_anchor(repository, 99, facts, fx))

    assert reported_id == 7
    assert converted_id == 8
    assert repository.report_insert is not None
    sql, parameters = repository.report_insert
    assert "other_shares_investment_reported" in sql
    assert parameters[-1] == "3936000"


def test_report_parser_fails_closed_when_balance_sheet_does_not_reconcile() -> None:
    broken = FIRST_HALF_2025.replace("Total equity 132,194", "Total equity 120,000")
    result = parse_otello_financial_report(broken)
    assert result["valid"] is False
    assert any(issue.startswith("balance_sheet_not_balanced:") for issue in result["issues"])


def test_post_grant_report_requires_option_liability_and_stock_compensation() -> None:
    report = SECOND_HALF_2025.replace("Options liabilities 4,408 -\n", "").replace(
        "Stock-based compensation expenses 4,427 - 4,427 -\n", ""
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

    assert 'PHASE = "16.2"' in scheduled
    assert "process_pending_otello_reports" in scheduled
    assert "archive_bucket=bindings.SOURCE_ARCHIVE" in entry
    assert '"ingest Otello financial reports"' in entry
    assert '"otello_reports": "NEWSWEB"' in full_refresh
    assert "STRICT_VALIDATION_FAIL_CLOSED" in report_ingestion
    assert "auto_apply_status" in report_ingestion
    assert "other_shares_investment_reported" in report_ingestion
    assert "company_news.processing_status IN ('APPLIED','IGNORED','REVIEW_REQUIRED')" in newsweb
    assert '"first-half report"' in newsweb
    assert '"second-half report"' in newsweb
    assert "document_type='OTELLO_FINANCIAL_REPORT'" in option_model
    assert 'metadata.get("auto_apply_status") != "APPLIED"' in option_model

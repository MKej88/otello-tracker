from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE = ROOT / "cloudflare"
if str(CLOUDFLARE) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE))

from src.report_status import report_status_summary  # noqa: E402


class FakeRepository:
    def __init__(self, *, with_report: bool) -> None:
        self.with_report = with_report

    async def first(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        if "FROM source_documents" in sql and "document_type=?" in sql and params == ("OTELLO_FINANCIAL_REPORT",):
            if not self.with_report:
                return None
            return {
                "id": 900,
                "title": "Otello Corporation ASA - First-Half Report 2026",
                "url": "https://example.test/report.pdf",
                "published_at": "2026-08-21T05:00:00Z",
                "fetched_at": "2026-08-21T05:02:00Z",
                "metadata_json": json.dumps(
                    {
                        "parser_version": "otello-financial-report-v2",
                        "message_id": 12345,
                        "auto_apply_status": "APPLIED",
                        "auto_apply_policy": "STRICT_VALIDATION_FAIL_CLOSED",
                        "validation": {"valid": True, "issues": []},
                        "pdf": {"r2_key": "newsweb/reports/2026-06-30/report.pdf", "content_sha256": "abc"},
                        "parsed_r2": {"r2_key": "newsweb/reports/2026-06-30/report.json"},
                        "facts": {
                            "report_date": "2026-06-30",
                            "source_period": "1H26",
                            "cash_usd": "18000000",
                            "other_net_assets_usd": "-3000000",
                            "option_liability_usd": "3500000",
                            "recurring_opex_usd": "1100000",
                        },
                    }
                ),
            }
        if "FROM company_news" in sql and "JOIN source_documents" not in sql:
            return {
                "headline": "Otello Corporation ASA - First-Half Report 2026" if self.with_report else None,
                "published_at": "2026-08-21T05:00:00Z" if self.with_report else None,
                "processing_status": "APPLIED" if self.with_report else "PARSED",
                "summary": "Automatisk innlest" if self.with_report else None,
                "notes": None,
            } if self.with_report else None
        if "JOIN source_documents sd" in sql and "company_news" in sql:
            return {
                "headline": "Otello Corporation ASA - First-Half Report 2026",
                "published_at": "2026-08-21T05:00:00Z",
                "processing_status": "APPLIED",
                "summary": "Automatisk innlest",
                "notes": None,
            }
        if "FROM cash_anchors" in sql:
            return {"as_of_date": "2025-12-31", "reported_amount": "15881000", "reported_currency": "USD"}
        if "FROM other_net_assets_reported_anchors" in sql:
            return {"as_of_date": "2025-12-31", "other_net_assets_reported": "-4530000", "option_liability_reported": "4408000"}
        if "document_type=?" in sql and params and params[0] == "ECONOMIC_NAV_COST_ANCHOR":
            if " = ?" in sql:
                return {"id": 701, "metadata_json": json.dumps({"amount_usd": "1100000"})}
            return {"id": 700, "metadata_json": json.dumps({"amount_usd": "1021000"})}
        if "FROM nav_snapshots" in sql:
            return {
                "nav_scope": "FULL",
                "nav_date": "2026-08-21",
                "nav_per_share_nok": "23.45",
                "nav_total_nok": "1590000000",
                "shares_outstanding": 67800000,
                "status": "DEGRADED",
            }
        return None


async def _waiting() -> dict[str, Any]:
    return await report_status_summary(FakeRepository(with_report=False))


async def _applied() -> dict[str, Any]:
    return await report_status_summary(FakeRepository(with_report=True))


def test_report_status_waits_without_auto_report_document() -> None:
    result = asyncio.run(_waiting())
    assert result["ready"] is False
    assert result["status"] == "WAITING"
    assert result["automation"]["pdf_auto_download"] is True
    assert result["automation"]["nav_rebuild"] is True


def test_report_status_exposes_archive_validation_and_anchor_changes() -> None:
    result = asyncio.run(_applied())
    assert result["ready"] is True
    assert result["status"] == "APPLIED"
    assert result["source_period"] == "1H26"
    assert result["archive"]["pdf_archived"] is True
    assert result["archive"]["parsed_archived"] is True
    assert result["validation"]["valid"] is True
    assert result["pipeline"]["anchors_applied"] is True
    assert result["pipeline"]["nav_rebuilt"] is True
    assert result["changes"]["cash"]["delta_usd"] == 2_119_000.0
    assert result["changes"]["other_net_assets"]["delta_usd"] == 1_530_000.0
    assert result["changes"]["option_liability"]["delta_usd"] == -908_000.0
    assert result["nav"]["nav_per_share_nok"] == 23.45


def test_frontend_mount_and_api_route_are_wired() -> None:
    app = (ROOT / "cloudflare" / "src" / "app.py").read_text(encoding="utf-8")
    main = (ROOT / "frontend" / "src" / "main.tsx").read_text(encoding="utf-8")
    panel = (ROOT / "frontend" / "src" / "ReportStatusPanel.tsx").read_text(encoding="utf-8")
    polling = (ROOT / "frontend" / "src" / "usePollingResource.ts").read_text(encoding="utf-8")

    assert '@app.get("/api/dashboard/report-status")' in app
    assert "report_status_summary" in app
    assert "<ReportStatusMount />" in main
    assert '"/api/dashboard/report-status"' in panel
    assert "usePollingResource<ReportStatus>" in panel
    assert "fetch(url" in polling
    assert "PDF hentet" in panel
    assert "NAV bygget på nytt" in panel

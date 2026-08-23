from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "cloudflare" / "migrations" / "0014_requeue_otello_1h26_report.sql"


def test_otello_1h26_requeue_is_narrow_and_parser_version_guarded() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "UPDATE company_news" in sql
    assert "category = 'RESULTS'" in sql
    assert "processing_status = 'REVIEW_REQUIRED'" in sql
    assert "processing_status = 'PARSED'" in sql
    assert "published_at" in sql
    assert ">= '2026-08-20'" in sql
    assert "LIKE '%otello-financial-report-v2%'" in sql
    assert "otello-financial-report-v3" in sql

    # Never broadly reopen APPLIED/IGNORED rows or unrelated manual review cases.
    assert "UPDATE company_news SET processing_status = 'PARSED'" not in sql
    assert "WHERE category = 'RESULTS'" in sql

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
if str(CLOUDFLARE_SRC) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE_SRC))

from newsweb_client import NewsWebAttachment, NewsWebMessage  # noqa: E402
from newsweb_daily_buybacks import (  # noqa: E402
    _attachment_candidates,
    _has_transaction_name_hint,
)


def _message(attachments: list[NewsWebAttachment]) -> NewsWebMessage:
    return NewsWebMessage(
        message_id=679898,
        news_id=None,
        title="Otello Corporation - Share buyback program status",
        body="weekly buyback body",
        issuer_id=7759,
        issuer_sign="OTEC",
        issuer_name="Otello Corporation ASA",
        published_at="2026-08-14T08:00:00Z",
        markets=("XOSL",),
        category_ids=(),
        attachments=tuple(attachments),
        corrected_by_message_id=0,
        correction_for_message_id=0,
        client_announcement_id=None,
    )


def test_nonstandard_or_blank_attachment_names_remain_candidates() -> None:
    message = _message(
        [
            NewsWebAttachment(11, "weekly-report.pdf"),
            NewsWebAttachment(12, ""),
            NewsWebAttachment(13, "OTEC Transaksjonsoversikt.pdf"),
        ]
    )

    candidates = _attachment_candidates(message)

    assert [item.attachment_id for item in candidates] == [13, 11, 12]
    assert _has_transaction_name_hint(candidates[0]) is True
    assert {item.attachment_id for item in candidates} == {11, 12, 13}


def test_attachment_fallback_is_content_reconciled_and_not_silent() -> None:
    source = (CLOUDFLARE_SRC / "newsweb_daily_buybacks.py").read_text(encoding="utf-8")

    assert "CONTENT_RECONCILIATION_FALLBACK" in source
    assert "for attachment in candidates:" in source
    assert "validate_daily_buybacks(daily, parsed)" in source
    assert "ingen kunne avstemmes som transaksjons-PDF mot ukemeldingen" in source


def test_dashboard_surfaces_share_count_and_nav_reconciliation() -> None:
    backend = (CLOUDFLARE_SRC / "dashboard_service.py").read_text(encoding="utf-8")
    frontend = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")

    assert '"share_count": latest_share_count' in backend
    assert '"used_in_nav"' in backend
    assert "Egne aksjer" in frontend
    assert "Utestående aksjer (NAV)" in frontend
    assert "Sist bekreftet aksjetall" in frontend
    assert "Aksjetall mot siste kilde" in frontend

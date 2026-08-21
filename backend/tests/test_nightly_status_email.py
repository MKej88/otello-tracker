from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
CLOUDFLARE_TOOLS = ROOT / "cloudflare" / "tools"
for path in (CLOUDFLARE_SRC, CLOUDFLARE_TOOLS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from render_production_config import render_config  # noqa: E402
from status_email import build_status_email  # noqa: E402


def _base_config() -> dict:
    return json.loads((ROOT / "cloudflare" / "wrangler.jsonc").read_text(encoding="utf-8"))


def _render(**overrides) -> dict:
    values = {
        "worker_name": "otello-tracker",
        "d1_database_id": "00000000-0000-0000-0000-000000000123",
        "d1_database_name": "otello-nav",
        "r2_bucket_name": "otello-source-archive",
        "custom_domain": "nav.example.com",
    }
    values.update(overrides)
    return render_config(_base_config(), **values)


def test_success_email_contains_operational_and_investor_status() -> None:
    message = build_status_email(
        {
            "status": "SUCCESS",
            "target_date": "2026-08-21",
            "records_written": 17,
            "source_health": {
                "NORGES_BANK": "OK",
                "B3": "OK",
                "CVM": "OK",
                "BEMOBI_IR": "OK",
                "NEWSWEB": "OK",
                "EURONEXT": "OK",
            },
            "preflight": {"ready": True, "blockers": [], "warnings": []},
            "critical_errors": [],
        },
        economic={
            "ready": True,
            "as_of_date": "2026-08-21",
            "nav_per_share": 31.42,
            "discount_pct": 17.8,
            "conservative_nav_per_share": 30.11,
        },
        started_at="2026-08-22T03:35:00Z",
        finished_at="2026-08-22T03:36:14Z",
        public_url="https://nav.example.com/",
    )

    assert message["subject"] == "Otello Tracker – nattkjøring OK – 2026-08-21"
    assert "Kjøretid: 1 min 14 sek" in message["text"]
    assert "Datakilder: 6/6 OK" in message["text"]
    assert "Økonomisk NAV: 31,42 kr/aksje" in message["text"]
    assert "Rabatt: 17,8 %" in message["text"]
    assert "Dashboard: https://nav.example.com/" in message["text"]


def test_failure_email_surfaces_critical_error_without_nav() -> None:
    message = build_status_email(
        {
            "status": "FAILED",
            "target_date": "2026-08-21",
            "source_health": {"NEWSWEB": "DOWN"},
            "critical_errors": [{"step": "newsweb", "error": "source unavailable"}],
            "preflight": {"ready": False, "blockers": [{"name": "source"}], "warnings": []},
        },
        economic={"ready": False, "reason": "missing_full_nav_row"},
    )

    assert "nattkjøring FEILET" in message["subject"]
    assert "NewsWeb: DOWN" in message["text"]
    assert "Preflight: FEILET" in message["text"]
    assert "newsweb: source unavailable" in message["text"]
    assert "Investor-NAV: ikke klar" in message["text"]


def test_production_email_binding_is_optional_and_restricted() -> None:
    without_email = _render()
    assert "send_email" not in without_email

    with_email = _render(
        status_email_to="owner@example.net",
        status_email_from="otello@example.com",
        public_url="https://nav.example.com/",
    )
    assert with_email["send_email"] == [
        {
            "name": "STATUS_EMAIL",
            "destination_address": "owner@example.net",
            "allowed_sender_addresses": ["otello@example.com"],
        }
    ]
    assert with_email["vars"]["STATUS_EMAIL_TO"] == "owner@example.net"
    assert with_email["vars"]["STATUS_EMAIL_FROM"] == "otello@example.com"
    assert with_email["vars"]["PUBLIC_URL"] == "https://nav.example.com"


def test_production_email_configuration_requires_sender_and_recipient_together() -> None:
    with pytest.raises(ValueError, match="må settes sammen"):
        _render(status_email_to="owner@example.net")

    with pytest.raises(ValueError, match="må settes sammen"):
        _render(status_email_from="otello@example.com")

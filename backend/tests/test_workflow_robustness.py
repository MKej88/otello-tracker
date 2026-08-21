from __future__ import annotations

import ast
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
if str(CLOUDFLARE_SRC) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE_SRC))

from full_refresh import (  # noqa: E402
    _critical_workflow_errors,
    _source_group_health,
)
from job_lock import LOCK_KEY, renew_refresh_lock  # noqa: E402


class _LeaseRepository:
    def __init__(self, value: str | None) -> None:
        self.value = value

    async def run(self, sql: str, parameters=()):
        normalized = " ".join(sql.split()).upper()
        if normalized.startswith("UPDATE RUNTIME_STATE"):
            renewed_token, key, old_token = parameters
            assert key == LOCK_KEY
            if self.value == old_token:
                self.value = renewed_token
            return None
        raise AssertionError(sql)

    async def first(self, sql: str, parameters=()):
        assert parameters == (LOCK_KEY,)
        if self.value is None:
            return None
        return {"value": self.value}


def test_writer_lease_renewal_is_compare_and_swap() -> None:
    original = "full:2026-08-20:workflow_manual|2026-08-20T21:00:00Z"
    repository = _LeaseRepository(original)
    renewed = asyncio.run(
        renew_refresh_lock(
            repository,
            original,
            ttl_seconds=3 * 60 * 60,
            now=datetime(2026, 8, 20, 20, 30, tzinfo=UTC),
        )
    )

    assert renewed["renewed"] is True
    assert renewed["token"] == "full:2026-08-20:workflow_manual|2026-08-20T23:30:00Z"
    assert repository.value == renewed["token"]

    lost = asyncio.run(
        renew_refresh_lock(
            repository,
            original,
            ttl_seconds=3 * 60 * 60,
            now=datetime(2026, 8, 20, 20, 31, tzinfo=UTC),
        )
    )
    assert lost["renewed"] is False
    assert lost["reason"] == "lease_lost"
    assert lost["held_by"] == "full:2026-08-20:workflow_manual"


def test_newsweb_health_is_aggregated_and_attachment_failure_only_degrades() -> None:
    results = {
        "newsweb": {"status": "ok"},
        "newsweb_attachments": {"status": "error", "error": "PDF archive unavailable"},
        "otello_reports": {"status": "skipped", "reason": "no_pending_reports"},
    }
    health, components = _source_group_health("NEWSWEB", results)
    assert health == "DEGRADED"
    assert components == {
        "newsweb": "OK",
        "newsweb_attachments": "DOWN",
        "otello_reports": "OK",
    }


def test_newsweb_report_review_is_critical() -> None:
    results = {
        "newsweb": {"status": "ok"},
        "newsweb_attachments": {"status": "ok"},
        "otello_reports": {"status": "ok", "review_required": 1},
    }
    health, _ = _source_group_health("NEWSWEB", results)
    critical = _critical_workflow_errors(
        results,
        {"status": "ok"},
        {"ready": True, "blockers": []},
    )
    assert health == "DOWN"
    assert any(item["step"] == "otello_reports" for item in critical)


def test_preflight_and_nav_are_fail_closed_but_secondary_sources_are_not() -> None:
    results = {
        "cvm": {"status": "error", "error": "temporary CVM failure"},
        "bemobi_web": {"status": "partial"},
    }
    assert _critical_workflow_errors(
        results,
        {"status": "ok"},
        {"ready": True, "blockers": []},
    ) == []

    critical = _critical_workflow_errors(
        results,
        {"status": "partial"},
        {"ready": False, "blockers": [{"name": "cash", "status": "FAIL"}]},
    )
    assert {item["step"] for item in critical} == {"nav", "preflight"}


def test_full_workflow_renews_lease_and_releases_latest_token() -> None:
    entry = (ROOT / "cloudflare" / "src" / "entry.py").read_text(encoding="utf-8")
    assert "renew_refresh_lock" in entry
    assert 'await renew_lock("after Norges Bank")' in entry
    assert 'await renew_lock(f"after Norges Bank history {chunk_year}")' in entry
    assert 'await renew_lock("after Otello reports")' in entry
    assert "release_refresh_lock(repository, lock_token)" in entry


def test_workflow_steps_do_not_capture_state_with_default_arguments() -> None:
    entry_path = ROOT / "cloudflare" / "src" / "entry.py"
    tree = ast.parse(entry_path.read_text(encoding="utf-8"))
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        is_workflow_step = any(
            isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Attribute)
            and decorator.func.attr == "do"
            and isinstance(decorator.func.value, ast.Name)
            and decorator.func.value.id == "step"
            for decorator in node.decorator_list
        )
        has_defaults = bool(node.args.defaults) or any(
            default is not None for default in node.args.kw_defaults
        )
        if is_workflow_step and has_defaults:
            offenders.append(node.name)

    assert offenders == []

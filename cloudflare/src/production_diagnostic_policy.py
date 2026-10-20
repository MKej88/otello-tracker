"""Conservative severity policy for read-only Cloudflare D1 diagnostics.

A PARTIAL full refresh is not automatically harmless. Only explicitly validated,
secondary Bemobi-source degradation can be reported as a warning. The NAV audit,
freshness tests, and all other source checks must still pass.
"""

from __future__ import annotations

import json
from typing import Any

REQUIRED_SOURCE_CODES = frozenset({
    "NORGES_BANK", "YAHOO_FINANCE", "B3", "CVM",
    "BEMOBI_IR", "NEWSWEB", "EURONEXT",
})


def _object(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value or "{}")
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def secondary_bemobi_warning_candidate(
    *,
    full: dict,
    sources: list[dict],
    expected_target: str,
) -> bool:
    """Verify a *single* degraded Bemobi feed with healthy core, not any PARTIAL.

    Does not itself override independent market-freshness or NAV-audit results.
    The caller must require all other checks to be green before using it.
    """
    if full.get("status") not in {"SUCCESS", "PARTIAL"}:
        return False
    if full.get("error_message"):
        return False

    metadata = _object(full.get("metadata_json"))
    if metadata.get("target_date") != expected_target:
        return False
    if metadata.get("critical_errors") != []:
        return False
    if _object(metadata.get("preflight")).get("ready") is not True:
        return False
    if _object(metadata.get("nav")).get("status") != "ok":
        return False
    if _object(metadata.get("archive")).get("status") == "error":
        return False

    health = _object(metadata.get("source_health"))
    # Never assume that absent status or another degraded source is harmless.
    if not REQUIRED_SOURCE_CODES.issubset(health):
        return False
    if health.get("BEMOBI_IR") != "DEGRADED":
        return False
    if any(health.get(code) != "OK" for code in REQUIRED_SOURCE_CODES - {"BEMOBI_IR"}):
        return False

    by_source = {row.get("code"): row for row in sources}
    if any(code not in by_source for code in REQUIRED_SOURCE_CODES):
        return False
    if by_source["BEMOBI_IR"].get("status") != "DEGRADED":
        return False
    if any(by_source[code].get("status") != "OK"
           for code in REQUIRED_SOURCE_CODES - {"BEMOBI_IR"}):
        return False

    bemobi = _object(_object(metadata.get("sources")).get("bemobi_web"))
    if "last-good-preserved" not in str(bemobi.get("policy") or ""):
        return False
    # The official ownership source and distribution/cash must be healthy.
    # A failed official IR or distribution feed remains a critical failure.
    if _object(bemobi.get("ir")).get("status") not in {"ok", "success", "skipped"}:
        return False
    if _object(bemobi.get("distribution_cash")).get("status") not in {
        "ok", "success", "skipped",
    }:
        return False
    # A known unavailable secondary release/broker/preview may use last good
    # facts, provided all primary data and NAV checks have passed.
    if bemobi.get("status") != "partial":
        return False
    return True


def diagnostic_severity(
    *,
    full_status: str,
    fast_status: str,
    fresh: bool,
    monitoring_unhealthy: bool,
    nav_audit_unhealthy: bool,
    secondary_bemobi_warning: bool,
    core_nav_status: str,
) -> str:
    """OK / ADVARSEL / AVVIK; unknown or stale critical data always fails."""
    if (
        fast_status not in {"SUCCESS", "PARTIAL"}
        or not fresh
        or monitoring_unhealthy
        or nav_audit_unhealthy
        or core_nav_status not in {"OK", "ESTIMATED", "BACKFILLED", "DEGRADED"}
    ):
        return "AVVIK"
    if full_status == "SUCCESS":
        return "ADVARSEL" if secondary_bemobi_warning else "OK"
    if full_status == "PARTIAL" and secondary_bemobi_warning:
        return "ADVARSEL"
    return "AVVIK"

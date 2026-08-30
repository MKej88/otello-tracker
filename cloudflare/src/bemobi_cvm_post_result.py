from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

from bemobi_cvm_financials import _LAST_ATTEMPT_KEY, refresh_bemobi_reported_net_income


async def _merge_harmonized_revenue_from_result(repository, *, period: str) -> dict[str, Any]:
    """Copy Bemobi's harmonized net revenue from the official result fact into TTM_QUARTER.

    Structured CVM DRE 3.01 is intentionally kept as statutory gross revenue. Bemobi's
    result release harmonizes M4U gross-up effects and is therefore stored separately so
    the dashboard can use the economically comparable revenue series without losing the
    regulatorily reported control number.
    """
    quarter = await repository.first(
        """
        SELECT id, payload_json FROM bemobi_investor_facts
        WHERE fact_type='TTM_QUARTER' AND fact_key=?
        LIMIT 1
        """,
        (period,),
    )
    if quarter is None:
        return {"status": "skipped", "reason": "ttm_quarter_missing", "rows_written": 0}

    result_fact = await repository.first(
        """
        SELECT payload_json, source_name, source_url, published_date
        FROM bemobi_investor_facts
        WHERE fact_type='RESULT' AND fact_key=?
        LIMIT 1
        """,
        (period,),
    )
    if result_fact is None:
        return {"status": "skipped", "reason": "result_fact_missing", "rows_written": 0}

    try:
        result_payload = json.loads(str(result_fact.get("payload_json") or "{}"))
        quarter_payload = json.loads(str(quarter.get("payload_json") or "{}"))
    except json.JSONDecodeError:
        return {"status": "error", "reason": "invalid_fact_json", "rows_written": 0}

    revenue = result_payload.get("adjusted_net_revenue_mbrl")
    if not isinstance(revenue, (int, float)) or revenue <= 0:
        return {
            "status": "skipped",
            "reason": "harmonized_revenue_missing",
            "rows_written": 0,
        }

    updates = {
        "harmonized_net_revenue_mbrl": round(float(revenue), 6),
        "harmonized_net_revenue_source": "Bemobi result release via CVM",
        "harmonized_net_revenue_source_url": result_fact.get("source_url"),
        "harmonized_net_revenue_quality": "OFFICIAL_RESULT_HARMONIZED",
        "harmonized_net_revenue_as_of_date": result_payload.get("period_end"),
        "harmonized_net_revenue_published_date": result_fact.get("published_date"),
    }
    changed = any(quarter_payload.get(key) != value for key, value in updates.items())
    if not changed:
        return {"status": "unchanged", "rows_written": 0, "value_mbrl": float(revenue)}

    quarter_payload.update(updates)
    await repository.run(
        """
        UPDATE bemobi_investor_facts
        SET payload_json=?, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
        WHERE id=?
        """,
        (
            json.dumps(quarter_payload, ensure_ascii=False, sort_keys=True),
            int(quarter["id"]),
        ),
    )
    return {"status": "updated", "rows_written": 1, "value_mbrl": float(revenue)}


async def refresh_cvm_financials_after_new_result(
    repository,
    *,
    target_date: str,
    period: str,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> dict[str, Any]:
    """Re-check structured CVM financials after a new result created its TTM quarter.

    The normal CVM financial refresh runs before the Bemobi result-release parser in the
    nightly workflow. On a result night that means the first pass can see the new ITR data
    before the matching ``TTM_QUARTER`` fact exists and therefore has nowhere to merge it.

    Once the result parser has created that quarter, persist Bemobi's harmonized revenue
    separately from statutory CVM 3.01, invalidate only the missing-quarter attempt throttle
    and run one immediate second CVM pass. The normal two-day retry cadence is restored by
    the called refresher if CVM Open Data has not published the new quarter yet.
    """
    quarter = await repository.first(
        """
        SELECT id FROM bemobi_investor_facts
        WHERE fact_type='TTM_QUARTER' AND fact_key=?
        LIMIT 1
        """,
        (period,),
    )
    if quarter is None:
        return {
            "status": "skipped",
            "reason": "new_result_quarter_fact_missing",
            "trigger_period": period,
            "rows_written": 0,
            "retry_throttle_reset": False,
        }

    harmonized_revenue = await _merge_harmonized_revenue_from_result(
        repository,
        period=period,
    )

    await repository.run(
        "DELETE FROM runtime_state WHERE key=?",
        (_LAST_ATTEMPT_KEY,),
    )
    result = await refresh_bemobi_reported_net_income(
        repository,
        target_date=target_date,
        fetcher=fetcher,
    )
    fact_status = result.get("fact_status") or {}
    return {
        **result,
        "rows_written": int(result.get("rows_written") or 0)
        + int(harmonized_revenue.get("rows_written") or 0),
        "trigger": "new_result_release",
        "trigger_period": period,
        "trigger_period_status": fact_status.get(period, "not_in_cvm_archive"),
        "harmonized_revenue": harmonized_revenue,
        "retry_throttle_reset": True,
    }

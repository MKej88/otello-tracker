from __future__ import annotations

from typing import Any, Awaitable, Callable

from bemobi_cvm_financials import _LAST_ATTEMPT_KEY, refresh_bemobi_reported_net_income


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

    Once the result parser has created that quarter, invalidate only the missing-quarter
    attempt throttle and run one immediate second pass. The normal two-day retry cadence is
    restored by the called refresher if CVM Open Data has not published the new quarter yet.
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
        "trigger": "new_result_release",
        "trigger_period": period,
        "trigger_period_status": fact_status.get(period, "not_in_cvm_archive"),
        "retry_throttle_reset": True,
    }

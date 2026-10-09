"""Keep last-good SGS observations through short upstream outages."""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta
from typing import Any

import brazil_dashboard as base

# This is time since a successful fetch, not the age of a monthly observation.
MAX_CACHE_AGE = timedelta(days=7)


def _valid_metric(metric: Any, *, as_of_date: str) -> bool:
    if not isinstance(metric, dict):
        return False
    try:
        observation = date.fromisoformat(str(metric.get("date")))
        value = metric.get("value")
        return (
            observation <= date.fromisoformat(as_of_date)
            and isinstance(value, (int, float))
            and math.isfinite(value)
        )
    except (TypeError, ValueError):
        return False


async def resolve_macro_metrics(repository: Any, result: dict[str, Any]) -> None:
    """Restore missing metrics before deriving signals and investor summaries."""
    as_of_date = result["as_of_date"]
    fetched_at = result["generated_at"]
    now = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
    metrics = result.setdefault("metrics", {})
    statuses = result.setdefault("source_status", {})
    for key in base.SERIES:
        state_key = f"brazil.macro.{key}.v1"
        status = statuses.setdefault(key, {})
        metric = metrics.get(key)
        try:
            if _valid_metric(metric, as_of_date=as_of_date):
                payload = json.dumps({"metric": metric, "fetched_at": fetched_at})
                await repository.run(
                    """INSERT INTO runtime_state(key, value, updated_at) VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        value=excluded.value, updated_at=excluded.updated_at
                    WHERE julianday(excluded.updated_at) >= julianday(runtime_state.updated_at)
                        AND json_extract(excluded.value, '$.metric.date') >=
                            json_extract(runtime_state.value, '$.metric.date')""",
                    (state_key, payload, fetched_at),
                )
                continue
            row = await repository.first(
                "SELECT value FROM runtime_state WHERE key = ?", (state_key,)
            )
            cached = json.loads(row["value"]) if row else None
            if not isinstance(cached, dict):
                continue
            metric = cached.get("metric")
            last_success = datetime.fromisoformat(
                str(cached.get("fetched_at")).replace("Z", "+00:00")
            )
            if (
                last_success.tzinfo is None
                or now.tzinfo is None
                or not timedelta(0) <= now - last_success <= MAX_CACHE_AGE
                or not _valid_metric(metric, as_of_date=as_of_date)
            ):
                continue
            metrics[key] = dict(metric, fallback_cached=True, last_success_at=cached["fetched_at"])
            status.update(
                ready=True, live_ready=False, fallback=True,
                date=metric["date"], last_success_at=cached["fetched_at"],
            )
        except Exception as exc:
            # D1 failures must not discard usable live source data.
            status["cache_error"] = f"{type(exc).__name__}: {exc}"
    result["ready"] = bool(metrics)

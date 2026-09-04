from __future__ import annotations

from datetime import UTC, datetime

from entry import Default as BaseDefault
from entry import FullRefreshWorkflow, R2SnapshotDrillWorkflow

FAST_REFRESH_CRON = "*/30 * * * *"
MEDIA_LOCK_TTL_SECONDS = 10 * 60
MEDIA_JOB_NAME = "bemobi_media_refresh"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _media_job_status(result: dict | None) -> str:
    status = str((result or {}).get("status") or "error").lower()
    if status == "ok":
        return "SUCCESS"
    if status in {"partial", "skipped"}:
        return "PARTIAL"
    return "FAILED"


def _media_error_message(result: dict | None) -> str | None:
    if not isinstance(result, dict):
        return "Media refresh returned no result"
    direct = str(result.get("error") or result.get("reason") or "").strip()
    if direct:
        return direct[:1000]
    errors = [
        *(result.get("feed_errors") or []),
        *(result.get("translation_errors") or []),
    ]
    messages = [str(item.get("error") or "").strip() for item in errors if isinstance(item, dict)]
    message = "; ".join(value for value in messages if value)
    return message[:1000] or None


class Default(BaseDefault):
    async def scheduled(self, controller, env, ctx):
        result = await super().scheduled(controller, env, ctx)
        if str(controller.cron) != FAST_REFRESH_CRON:
            return result

        bindings = env if env is not None else self.env
        media_result = None
        lock_token = None
        media_job_id = None
        repository = None
        try:
            from bemobi_media_news import refresh_bemobi_media_news
            from job_lock import acquire_refresh_lock, release_refresh_lock
            from performance_repository import PerformanceD1WriteRepository

            repository = PerformanceD1WriteRepository(bindings.DB)
            lock = await acquire_refresh_lock(
                repository,
                owner=f"media:{controller.scheduledTime}",
                ttl_seconds=MEDIA_LOCK_TTL_SECONDS,
            )
            if not lock.get("acquired"):
                media_result = {
                    "status": "skipped",
                    "reason": "refresh_lock_held",
                    "held_by": lock.get("held_by"),
                    "expires_at": lock.get("expires_at"),
                    "written": 0,
                }
            else:
                lock_token = lock.get("token")
                media_job_id = await repository.start_job(
                    job_name=MEDIA_JOB_NAME,
                    started_at=_now_iso(),
                    metadata={
                        "trigger": "cloudflare_cron",
                        "cron": FAST_REFRESH_CRON,
                    },
                )
                try:
                    media_result = await refresh_bemobi_media_news(
                        repository,
                        ai_binding=getattr(bindings, "AI", None),
                    )
                except Exception as exc:
                    media_result = {
                        "status": "error",
                        "error": str(exc)[:1000] or type(exc).__name__,
                        "error_type": type(exc).__name__,
                        "written": 0,
                        "non_critical": True,
                    }
                finally:
                    if media_job_id is not None:
                        try:
                            metadata = {
                                "trigger": "cloudflare_cron",
                                "cron": FAST_REFRESH_CRON,
                                **(media_result if isinstance(media_result, dict) else {}),
                            }
                            await repository.finish_job(
                                media_job_id,
                                finished_at=_now_iso(),
                                status=_media_job_status(media_result),
                                records_written=int((media_result or {}).get("written") or 0),
                                error_message=_media_error_message(media_result),
                                metadata=metadata,
                            )
                        except Exception as exc:
                            if isinstance(media_result, dict):
                                media_result["status_persist_error"] = str(exc)[:500]
        except Exception as exc:
            media_result = {
                "status": "error",
                "error": str(exc)[:1000] or type(exc).__name__,
                "error_type": type(exc).__name__,
                "written": 0,
                "non_critical": True,
            }
        finally:
            if lock_token is not None and repository is not None:
                try:
                    from job_lock import release_refresh_lock

                    await release_refresh_lock(repository, lock_token)
                except Exception as exc:
                    if isinstance(media_result, dict):
                        media_result["lock_release_error"] = str(exc)[:500]

        if isinstance(result, dict):
            enriched = dict(result)
            enriched["bemobi_media"] = media_result
            return enriched
        return {"scheduled": result, "bemobi_media": media_result}


__all__ = [
    "Default",
    "FullRefreshWorkflow",
    "R2SnapshotDrillWorkflow",
]

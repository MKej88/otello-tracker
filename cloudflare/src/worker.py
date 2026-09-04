from __future__ import annotations

from entry import Default as BaseDefault
from entry import FullRefreshWorkflow, R2SnapshotDrillWorkflow

FAST_REFRESH_CRON = "*/30 * * * *"
MEDIA_LOCK_TTL_SECONDS = 10 * 60


class Default(BaseDefault):
    async def scheduled(self, controller, env, ctx):
        result = await super().scheduled(controller, env, ctx)
        if str(controller.cron) != FAST_REFRESH_CRON:
            return result

        bindings = env if env is not None else self.env
        media_result = None
        lock_token = None
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
            if lock_token is not None:
                try:
                    from job_lock import release_refresh_lock
                    from performance_repository import PerformanceD1WriteRepository

                    await release_refresh_lock(
                        PerformanceD1WriteRepository(bindings.DB),
                        lock_token,
                    )
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

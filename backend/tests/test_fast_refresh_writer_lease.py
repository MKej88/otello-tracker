from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
if str(CLOUDFLARE_SRC) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE_SRC))

import scheduled  # noqa: E402


def test_fast_cron_acquires_from_actual_time_renews_and_releases_latest_token(monkeypatch) -> None:
    events: list[tuple] = []

    class FakeRepository:
        def __init__(self, database):
            self.database = database

    async def acquire(repository, **kwargs):
        events.append(("acquire", kwargs))
        return {
            "acquired": True,
            "token": "fast-owner|lease-1",
            "held_by": "fast-owner",
            "expires_at": "lease-1",
        }

    async def renew(repository, token, **kwargs):
        events.append(("renew", token, kwargs))
        suffix = sum(1 for event in events if event[0] == "renew") + 1
        return {
            "renewed": True,
            "token": f"fast-owner|lease-{suffix}",
            "held_by": "fast-owner",
            "expires_at": f"lease-{suffix}",
        }

    async def release(repository, token):
        events.append(("release", token))
        return True

    async def fake_run_fast_refresh(
        database,
        *,
        archive_bucket=None,
        scheduled_time_ms=None,
        renew_lock=None,
    ):
        assert renew_lock is not None
        await renew_lock("after OTEC")
        await renew_lock("after B3")
        return {"status": "SUCCESS"}

    monkeypatch.setattr(scheduled, "PerformanceD1WriteRepository", FakeRepository)
    monkeypatch.setattr(scheduled, "acquire_refresh_lock", acquire)
    monkeypatch.setattr(scheduled, "renew_refresh_lock", renew)
    monkeypatch.setattr(scheduled, "release_refresh_lock", release)
    monkeypatch.setattr(scheduled, "run_fast_refresh", fake_run_fast_refresh)

    result = asyncio.run(
        scheduled.run_scheduled(
            object(),
            cron=scheduled.FAST_REFRESH_CRON,
            archive_bucket=object(),
            scheduled_time_ms=1787506200000,
        )
    )

    assert result["status"] == "SUCCESS"
    acquire_kwargs = next(event[1] for event in events if event[0] == "acquire")
    assert "now" not in acquire_kwargs
    assert acquire_kwargs["ttl_seconds"] == scheduled.FAST_LOCK_TTL_SECONDS
    assert [event[1] for event in events if event[0] == "renew"] == [
        "fast-owner|lease-1",
        "fast-owner|lease-2",
    ]
    assert events[-1] == ("release", "fast-owner|lease-3")


def test_fast_cron_stops_when_writer_lease_is_lost(monkeypatch) -> None:
    released: list[str | None] = []

    class FakeRepository:
        def __init__(self, database):
            self.database = database

    async def acquire(repository, **kwargs):
        return {
            "acquired": True,
            "token": "fast-owner|lease-1",
            "held_by": "fast-owner",
            "expires_at": "lease-1",
        }

    async def renew(repository, token, **kwargs):
        return {
            "renewed": False,
            "token": None,
            "held_by": "another-writer",
            "expires_at": "later",
        }

    async def release(repository, token):
        released.append(token)
        return False

    async def fake_run_fast_refresh(
        database,
        *,
        archive_bucket=None,
        scheduled_time_ms=None,
        renew_lock=None,
    ):
        assert renew_lock is not None
        await renew_lock("after OTEC")
        raise AssertionError("unreachable")

    monkeypatch.setattr(scheduled, "PerformanceD1WriteRepository", FakeRepository)
    monkeypatch.setattr(scheduled, "acquire_refresh_lock", acquire)
    monkeypatch.setattr(scheduled, "renew_refresh_lock", renew)
    monkeypatch.setattr(scheduled, "release_refresh_lock", release)
    monkeypatch.setattr(scheduled, "run_fast_refresh", fake_run_fast_refresh)

    try:
        asyncio.run(
            scheduled.run_scheduled(
                object(),
                cron=scheduled.FAST_REFRESH_CRON,
                scheduled_time_ms=1787506200000,
            )
        )
    except RuntimeError as exc:
        assert "fast refresh writer lease lost at after OTEC" in str(exc)
    else:
        raise AssertionError("lost writer lease should abort the fast refresh")

    assert released == ["fast-owner|lease-1"]

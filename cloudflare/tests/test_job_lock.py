from __future__ import annotations

import asyncio
from typing import Any

from src.job_lock import LOCK_KEY, release_refresh_lock


class LockRepository:
    def __init__(self, value: str | None) -> None:
        self.value = value

    async def run(self, _sql: str, parameters: tuple[Any, ...]) -> None:
        key, token = parameters
        if key == LOCK_KEY and self.value == token:
            self.value = None

    async def first(
        self,
        _sql: str,
        _parameters: tuple[Any, ...],
    ) -> dict[str, str] | None:
        return {"value": self.value} if self.value is not None else None


def test_release_reports_success_when_owned_lock_is_deleted() -> None:
    token = "full:2026-08-30:workflow|2026-08-30T04:00:00Z"
    repository = LockRepository(token)

    assert asyncio.run(release_refresh_lock(repository, token)) is True
    assert repository.value is None


def test_release_reports_failure_when_another_owner_holds_lock() -> None:
    stale_token = "full:2026-08-30:workflow|2026-08-30T04:00:00Z"
    current_token = "fast:2026-08-30T04:30:00Z|2026-08-30T05:00:00Z"
    repository = LockRepository(current_token)

    assert asyncio.run(release_refresh_lock(repository, stale_token)) is False
    assert repository.value == current_token

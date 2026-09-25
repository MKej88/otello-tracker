from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cloudflare/src"))
from bemobi_agenda import agenda_events  # noqa: E402


class FailingRepository:
    async def first(self, sql, params=()):
        raise RuntimeError("D1 unavailable")


def test_agenda_cache_read_failure_is_not_hidden_by_bootstrap():
    with pytest.raises(RuntimeError, match="D1 unavailable"):
        asyncio.run(agenda_events(FailingRepository(), as_of_date="2026-09-25"))

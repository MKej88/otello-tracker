from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE = ROOT / "cloudflare"
if str(CLOUDFLARE) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE))

import src.nav_refresh as nav_refresh  # noqa: E402


def test_core_nav_loads_independent_inputs_concurrently(monkeypatch) -> None:
    started: list[str] = []
    all_started = asyncio.Event()

    def delayed_reader(name: str):
        async def read(*_args):
            started.append(name)
            if len(started) == 6:
                all_started.set()
            await asyncio.wait_for(all_started.wait(), timeout=0.5)
            return None

        return read

    monkeypatch.setattr(nav_refresh, "_preferred_price", delayed_reader("price"))
    monkeypatch.setattr(nav_refresh, "_nearest_fx", delayed_reader("fx"))
    monkeypatch.setattr(nav_refresh, "_holding", delayed_reader("holding"))
    monkeypatch.setattr(nav_refresh, "_share_count", delayed_reader("shares"))
    monkeypatch.setattr(nav_refresh, "_cash_for_date", delayed_reader("cash"))

    result = asyncio.run(nav_refresh.calculate_core_nav(object(), "2026-08-17"))

    assert len(started) == 6
    assert result == {
        "as_of_date": "2026-08-17",
        "ready": False,
        "missing": [
            "BMOB3 market price",
            "OTEC market price",
            "BRL/NOK",
            "Bemobi holding",
            "OTEC share count",
            "daily cash",
        ],
    }

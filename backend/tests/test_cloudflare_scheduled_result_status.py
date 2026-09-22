from __future__ import annotations

import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
if str(CLOUDFLARE_SRC) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE_SRC))

from scheduled import _safe_async_step  # noqa: E402


def test_safe_step_propagates_returned_error_status() -> None:
    async def returned_error() -> dict[str, str]:
        return {
            "status": "error",
            "error": "upstream svarte med ugyldige data",
            "error_type": "UpstreamDataError",
        }

    steps: dict[str, object] = {}
    errors: list[dict[str, str]] = []
    timings: dict[str, float] = {}

    result = asyncio.run(
        _safe_async_step(
            "market_data",
            returned_error,
            steps=steps,
            errors=errors,
            timings_ms=timings,
        )
    )

    assert result == steps["market_data"]
    assert errors == [
        {
            "step": "market_data",
            "error": "upstream svarte med ugyldige data",
            "error_type": "UpstreamDataError",
        }
    ]

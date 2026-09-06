from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from src.dashboard_hot_snapshot import build_dashboard_hot_snapshot


def test_snapshot_refresh_preserves_economic_nav_calculation_time() -> None:
    calculated_at = "2026-08-29T18:15:00Z"

    with (
        patch(
            "src.dashboard_hot_snapshot.dashboard_summary",
            new=AsyncMock(return_value={"ready": True}),
        ),
        patch(
            "src.dashboard_hot_snapshot.enrich_dashboard_summary",
            new=AsyncMock(return_value={"ready": True}),
        ),
        patch(
            "src.dashboard_hot_snapshot.economic_nav_summary",
            new=AsyncMock(return_value={"ready": True, "calculated_at": calculated_at}),
        ),
        patch(
            "src.dashboard_hot_snapshot.market_quote_details",
            new=AsyncMock(return_value={"ready": True}),
        ),
        patch(
            "src.dashboard_hot_snapshot.buyback_forecast",
            new=AsyncMock(return_value={"ready": True}),
        ),
        patch(
            "src.dashboard_hot_snapshot.overview_events",
            new=AsyncMock(return_value={"ready": True, "events": [], "calendar": []}),
        ),
        patch(
            "src.dashboard_hot_snapshot._now_iso",
            return_value="2026-08-31T10:00:00Z",
        ),
    ):
        result = asyncio.run(build_dashboard_hot_snapshot(object()))

    assert result["generated_at"] == "2026-08-31T10:00:00Z"
    assert result["economic"]["calculated_at"] == calculated_at

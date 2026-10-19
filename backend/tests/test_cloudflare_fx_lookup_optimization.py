from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE = ROOT / "cloudflare"
if str(CLOUDFLARE) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE))

from src.fx_dashboard import _on_or_before  # noqa: E402


def test_precomputed_fx_dates_preserve_historical_matching() -> None:
    start = date(2021, 1, 1)
    series = [
        {"date": (start + timedelta(days=day)).isoformat(), "rate": str(day + 100)}
        for day in range(0, 1900, 3)
    ]
    dates = [row["date"] for row in series]

    for day in range(-1, 1905, 7):
        target = (start + timedelta(days=day)).isoformat()
        previous = _on_or_before(series, target, max_lookback_days=7)
        optimized = _on_or_before(
            series, target, max_lookback_days=7, dates=dates
        )
        assert optimized == previous


def test_precomputed_fx_dates_do_not_use_expired_reference() -> None:
    series = [{"date": "2026-10-01", "rate": "1.20"}]
    assert _on_or_before(series, "2026-10-09", max_lookback_days=7, dates=["2026-10-01"]) is None
    assert _on_or_before(series, "2026-10-08", max_lookback_days=7, dates=["2026-10-01"]) == series[0]

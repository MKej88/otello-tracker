from __future__ import annotations

import importlib.util
from pathlib import Path

from app.estimated_nav_history import _history_start_point


def _points() -> list[dict[str, str]]:
    return [
        {"date": "2025-12-29"},
        {"date": "2026-01-02"},
        {"date": "2026-01-05"},
    ]


def test_ytd_prefers_prior_year_closing_point() -> None:
    start = _history_start_point(
        _points(),
        "2026-01-01",
        year_to_date=True,
    )

    assert start["date"] == "2025-12-29"


def test_regular_period_keeps_nearest_point_selection() -> None:
    start = _history_start_point(
        _points(),
        "2026-01-01",
        year_to_date=False,
    )

    assert start["date"] == "2026-01-02"


def test_cloudflare_ytd_prefers_prior_year_closing_point() -> None:
    source = (
        Path(__file__).resolve().parents[2]
        / "cloudflare"
        / "src"
        / "estimated_nav_history.py"
    )
    spec = importlib.util.spec_from_file_location(
        "cloudflare_estimated_nav_history", source
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    start = module._history_start_point(
        _points(),
        "2026-01-01",
        year_to_date=True,
    )

    assert start["date"] == "2025-12-29"

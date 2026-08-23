from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
if str(CLOUDFLARE_SRC) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE_SRC))

from d1_preflight import _investor_nav_is_valid  # noqa: E402


def _economic(**overrides):
    payload = {
        "ready": True,
        "as_of_date": "2026-08-21",
        "nav_per_share": 21.0,
        "accounting_nav_per_share": 21.5,
        "conservative_nav_per_share": 20.9,
    }
    payload.update(overrides)
    return payload


def test_investor_nav_preflight_accepts_current_ordered_nav() -> None:
    assert _investor_nav_is_valid(_economic(), dashboard_as_of_date="2026-08-21") is True


def test_investor_nav_preflight_rejects_conservative_nav_above_base() -> None:
    assert (
        _investor_nav_is_valid(
            _economic(conservative_nav_per_share=21.01),
            dashboard_as_of_date="2026-08-21",
        )
        is False
    )


def test_investor_nav_preflight_rejects_stale_or_incomplete_payload() -> None:
    assert _investor_nav_is_valid(_economic(), dashboard_as_of_date="2026-08-22") is False
    assert (
        _investor_nav_is_valid(
            _economic(conservative_nav_per_share=None),
            dashboard_as_of_date="2026-08-21",
        )
        is False
    )
    assert (
        _investor_nav_is_valid(
            _economic(nav_per_share=float("nan")),
            dashboard_as_of_date="2026-08-21",
        )
        is False
    )

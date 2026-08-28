from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.nav.other_net_assets import (  # noqa: E402
    _interpolated_base_ex_option as reference_interpolation,
)

if str(CLOUDFLARE_SRC) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE_SRC))

from nav_refresh import _interpolated_base_ex_option as worker_interpolation  # noqa: E402


def _post_grant_anchors() -> tuple[dict[str, str], dict[str, str]]:
    return (
        {
            "base_other_net_assets_reported": "2974000",
            "base_other_net_assets_ex_option_reported": "3288000",
            "option_liability_reported": "314000",
        },
        {
            "base_other_net_assets_reported": "2211000",
            "base_other_net_assets_ex_option_reported": "2933000",
            "option_liability_reported": "722000",
        },
    )


def test_post_grant_interval_interpolates_decomposed_ona() -> None:
    start_anchor, end_anchor = _post_grant_anchors()
    start_day = date(2025, 12, 31)
    end_day = date(2026, 6, 30)
    current = date(2026, 5, 28)

    elapsed = Decimal((current - start_day).days)
    span = Decimal((end_day - start_day).days)
    expected = Decimal("3288000") + (
        Decimal("2933000") - Decimal("3288000")
    ) * elapsed / span

    reference = reference_interpolation(
        start_anchor,
        end_anchor,
        start_day,
        end_day,
        current,
    )
    worker = worker_interpolation(
        start_anchor,
        end_anchor,
        start_day,
        end_day,
        current,
    )

    assert reference == expected
    assert worker == expected

    legacy_wrong = Decimal("2974000") + (
        Decimal("2211000") - Decimal("2974000")
    ) * elapsed / span
    assert expected != legacy_wrong


def test_post_grant_interpolation_is_continuous_into_report_anchor() -> None:
    start_anchor, end_anchor = _post_grant_anchors()
    start_day = date(2025, 12, 31)
    end_day = date(2026, 6, 30)

    expected_end = Decimal("2933000")
    assert reference_interpolation(
        start_anchor,
        end_anchor,
        start_day,
        end_day,
        end_day,
    ) == expected_end
    assert worker_interpolation(
        start_anchor,
        end_anchor,
        start_day,
        end_day,
        end_day,
    ) == expected_end

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"


def _load_news_events_module():
    sys.path.insert(0, str(CLOUDFLARE_SRC))
    try:
        spec = importlib.util.spec_from_file_location(
            "cloudflare_news_events_timezone_test",
            CLOUDFLARE_SRC / "news_events.py",
        )
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


def test_current_oslo_date_uses_norwegian_date_after_utc_midnight() -> None:
    module = _load_news_events_module()

    now = datetime(2026, 1, 15, 23, 30, tzinfo=UTC)

    assert module._current_oslo_date(now) == date(2026, 1, 16)


def test_current_oslo_date_handles_summer_time() -> None:
    module = _load_news_events_module()

    now = datetime(2026, 7, 15, 22, 30, tzinfo=UTC)

    assert module._current_oslo_date(now) == date(2026, 7, 16)

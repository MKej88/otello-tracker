from __future__ import annotations

import sys
import types
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

SOURCE_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SOURCE_DIR))
workers = types.ModuleType("workers")
workers.WorkflowEntrypoint = object
workers.WorkerEntrypoint = object
sys.modules.setdefault("workers", workers)

from entry import _workflow_target_date  # noqa: E402


class _AfterOsloMidnight(datetime):
    @classmethod
    def now(cls, tz=None):
        current = cls(2026, 9, 26, 22, 30, tzinfo=UTC)
        return current if tz is None else current.astimezone(tz)


def test_manual_workflow_uses_current_oslo_date() -> None:
    with patch("entry.datetime", _AfterOsloMidnight):
        target_date = _workflow_target_date({"instanceId": "manual-run"})

    assert target_date == "2026-09-27"

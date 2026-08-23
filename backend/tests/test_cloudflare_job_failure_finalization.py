from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

CLOUDFLARE_SRC = Path(__file__).resolve().parents[2] / "cloudflare" / "src"
if str(CLOUDFLARE_SRC) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE_SRC))

from repository import D1WriteRepository  # noqa: E402


class StubJobRepository(D1WriteRepository):
    def __init__(self, row):
        self.row = row
        self.finished = []

    async def first(self, sql, parameters=()):
        assert "FROM job_runs" in sql
        assert parameters == (42,)
        return dict(self.row) if self.row is not None else None

    async def finish_job(self, job_id, **kwargs):
        self.finished.append((job_id, kwargs))


def test_fail_job_if_running_marks_failed_and_preserves_metadata():
    repository = StubJobRepository(
        {
            "status": "RUNNING",
            "metadata_json": json.dumps(
                {"phase": "16.3", "trigger": "workflow_schedule:35 3 * * *"}
            ),
        }
    )

    updated = asyncio.run(
        repository.fail_job_if_running(
            42,
            finished_at="2026-08-23T05:46:41.000Z",
            error_message="Too many API requests",
            metadata={
                "target_date": "2026-08-22",
                "failure": {"step": "workflow", "error": "Too many API requests"},
            },
        )
    )

    assert updated is True
    assert len(repository.finished) == 1
    job_id, values = repository.finished[0]
    assert job_id == 42
    assert values["status"] == "FAILED"
    assert values["finished_at"] == "2026-08-23T05:46:41.000Z"
    assert values["records_written"] == 0
    assert values["error_message"] == "Too many API requests"
    assert values["metadata"]["phase"] == "16.3"
    assert values["metadata"]["trigger"] == "workflow_schedule:35 3 * * *"
    assert values["metadata"]["target_date"] == "2026-08-22"
    assert values["metadata"]["failure"]["step"] == "workflow"


def test_fail_job_if_running_does_not_overwrite_terminal_success():
    repository = StubJobRepository(
        {"status": "SUCCESS", "metadata_json": json.dumps({"phase": "16.3"})}
    )

    updated = asyncio.run(
        repository.fail_job_if_running(
            42,
            finished_at="2026-08-23T05:46:41.000Z",
            error_message="email failed after successful refresh",
        )
    )

    assert updated is False
    assert repository.finished == []


def test_full_workflow_exception_path_uses_guarded_failure_finalizer():
    source = (CLOUDFLARE_SRC / "entry.py").read_text(encoding="utf-8")
    assert '"finalize failed full refresh"' in source
    assert "fail_job_if_running(" in source
    assert source.index('"finalize failed full refresh"') < source.index(
        '"send nightly failure status email"'
    )

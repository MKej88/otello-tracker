"""Regression tests for unified read-only diagnostics routing."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from select_bemobi_diagnostics import changed_paths, select


@pytest.mark.parametrize(
    ("choice", "expected"),
    [
        ("fem-dokumenter", (True, False, False)),
        ("oversettelsesarkiv", (False, True, False)),
        ("cvm-kilder", (False, False, True)),
        ("alle", (True, True, True)),
    ],
)
def test_manual_choice(choice, expected):
    assert tuple(select("workflow_dispatch", choice).values()) == expected


def test_push_and_pr_keep_original_scope():
    assert select("push", changed={"tools/diagnose_bemobi_five_documents.py"}) == {
        "five": True, "archive": False, "rad": False,
    }
    assert select("push", changed={"tools/audit_bemobi_translation_archive.py"}) == {
        "five": False, "archive": True, "rad": False,
    }
    assert select("pull_request", changed={"tools/probe_bemobi_cvm_rad.py"}) == {
        "five": False, "archive": False, "rad": True,
    }
    assert select("pull_request", changed={"backend/tests/test_bemobi_five_document_diagnostic.py"})["five"]
    assert not select("push", changed={"tools/probe_bemobi_cvm_rad.py"})["rad"]


def test_missing_diff_fails_open_only_for_original_event_scope():
    assert select("push") == {"five": True, "archive": True, "rad": False}
    assert select("pull_request") == {"five": True, "archive": True, "rad": True}
    assert changed_paths("push", "invalid", "f" * 40) is None
    with pytest.raises(ValueError):
        select("workflow_dispatch", "invalid")


def test_production_jobs_are_separate_and_read_only():
    workflow = (ROOT / ".github/workflows/bemobi-diagnostics.yml").read_text()
    assert workflow.count("environment: production") == 2
    assert workflow.count("github.ref == 'refs/heads/main' && github.event_name != 'pull_request'") == 2
    assert "permissions:\n  contents: read" in workflow
    assert "secrets.CLOUDFLARE_API_TOKEN" not in workflow
    assert "CLOUDFLARE_API_TOKEN: ${{ secrets.CLOUDFLARE_READ_TOKEN }}" in workflow

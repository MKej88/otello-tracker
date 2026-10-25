"""Offline tests of the exact inline GitHub incident notifier (no network)."""
from __future__ import annotations

import ast
import json
import os
import textwrap
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/cloudflare-workflow-diagnostics.yml"


def incident_script():
    text = WORKFLOW.read_text(encoding="utf-8")
    marker = "      - name: Open or close dedicated incident issue"
    section = text.split(marker, 1)[1]
    script = section.split("          python3 - <<'PY'\n", 1)[1]
    script = script.split("\n          PY", 1)[0]
    return textwrap.dedent(script)


class FakeHTTP:
    def __init__(self, response):
        self.response = response

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return json.dumps(self.response).encode("utf-8")


class NotificationTests(unittest.TestCase):
    def test_inline_notifier_python_is_valid(self):
        ast.parse(incident_script())

    def exercise(self, result, found=None):
        calls = []

        def urlopen(req, timeout):
            method, url = req.get_method(), req.full_url
            payload = json.loads(req.data) if req.data else None
            calls.append((method, url, payload))
            if "/search/issues?" in url:
                return FakeHTTP({"items": [found] if found else []})
            if method == "POST":
                return FakeHTTP({"number": 2345})
            return FakeHTTP({"state": payload.get("state") if payload else None})

        env = {
            "INCIDENT_KIND": "nightly",
            "INCIDENT_RESULT": result,
            "GITHUB_REPOSITORY": "MKej88/otello-tracker",
            "RUN_URL": "https://github.com/MKej88/otello-tracker/actions/runs/123",
            "GITHUB_TOKEN": "test-value-only",
        }
        with patch.dict(os.environ, env), patch("urllib.request.urlopen", side_effect=urlopen):
            with redirect_stdout(StringIO()):
                exec(compile(incident_script(), str(WORKFLOW), "exec"), {"__name__": "__main__"})
        return calls

    def test_opens_only_one_red_incident_without_sensitive_log_content(self):
        calls = self.exercise("failure")
        creation = [c for c in calls if c[0] == "POST"]
        self.assertEqual(len(creation), 1)
        self.assertEqual(creation[0][2]["assignees"], ["MKej88"])
        self.assertIn("otello-production-incident:nightly", creation[0][2]["body"])

    def test_does_not_duplicate_open_incident(self):
        existing = {
            "number": 123, "state": "open",
            "body": "<!-- otello-production-incident:nightly -->",
        }
        calls = self.exercise("failure", found=existing)
        self.assertEqual([c[0] for c in calls], ["GET"])

    def test_only_success_closes_existing_incident(self):
        existing = {
            "number": 123, "state": "open",
            "body": "<!-- otello-production-incident:nightly -->",
        }
        calls = self.exercise("success", found=existing)
        updates = [c for c in calls if c[0] == "PATCH"]
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0][2]["state"], "closed")

    def test_success_without_incident_is_noop(self):
        calls = self.exercise("success")
        self.assertEqual([c[0] for c in calls], ["GET"])


if __name__ == "__main__":
    unittest.main()

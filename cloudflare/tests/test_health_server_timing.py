"""The health probe must expose D1 timing without weakening the database check."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException, Response

from src import app as api


class HealthTimingTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_reports_d1_duration_and_retains_revision(self) -> None:
        repository = SimpleNamespace(first=AsyncMock(return_value={"ok": 1}))
        request = SimpleNamespace(scope={
            "env": SimpleNamespace(DEPLOYMENT_REVISION="test-revision"),
        })
        response = Response()
        with patch.object(api, "_repository", return_value=repository):
            result = await api.health(request, response)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["revision"], "test-revision")
        repository.first.assert_awaited_once_with("SELECT 1 AS ok")
        self.assertRegex(response.headers["server-timing"], r"^d1;dur=\d+\.\d{2}$")

    async def test_failure_remains_an_http_503(self) -> None:
        repository = SimpleNamespace(first=AsyncMock(return_value=None))
        request = SimpleNamespace(scope={"env": SimpleNamespace()})
        response = Response()
        with patch.object(api, "_repository", return_value=repository):
            with self.assertRaises(HTTPException) as exc:
                await api.health(request, response)

        self.assertEqual(exc.exception.status_code, 503)
        self.assertNotIn("server-timing", response.headers)


if __name__ == "__main__":
    unittest.main()

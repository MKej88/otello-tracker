from __future__ import annotations

import sys
import types

from workers import WorkerEntrypoint

# Cloudflare's Python Worker loader exposes files below `src/` as top-level modules.
# The same source tree is also imported as the `src` package by CPython parity tests.
# Keep the shared buyback service package-compatible by aliasing only its calendar
# dependency before the top-level Worker modules are imported.
import oslo_calendar

_src_package = sys.modules.get("src")
if _src_package is None:
    _src_package = types.ModuleType("src")
    _src_package.__path__ = []
    sys.modules["src"] = _src_package
sys.modules.setdefault("src.oslo_calendar", oslo_calendar)

from app import app  # noqa: E402


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        import asgi

        return await asgi.fetch(app, request.js_object, self.env)

"""Bounded Worker-entrypoint timing headers, without request/customer data.

Only durations are exposed. Timers start when Python enters Default.fetch;
Cloudflare startup before the entrypoint is deliberately NOT measured.
"""
from __future__ import annotations

from typing import Any


def worker_timing_header(*, fetch_ms: float, asgi_import_ms: float, asgi_ms: float) -> str:
    def duration(label: str, value: float) -> str:
        # Non-negative, bounded and rounded Server-Timing numeric value.
        safe = max(0.0, min(float(value), 120_000.0))
        return f"{label};dur={safe:.2f}"

    return ", ".join((
        duration("otello_fetch", fetch_ms),
        duration("otello_asgi_import", asgi_import_ms),
        duration("otello_asgi", asgi_ms),
    ))


def append_worker_timing(
    response: Any, *, fetch_ms: float, asgi_import_ms: float, asgi_ms: float
) -> Any:
    """Append to the existing endpoint/ASGI Server-Timing on a JS Response.

    Does not alter response status, body, cache policy or any business data.
    """
    headers = response.headers
    existing = headers.get("Server-Timing")
    measurement = worker_timing_header(
        fetch_ms=fetch_ms, asgi_import_ms=asgi_import_ms, asgi_ms=asgi_ms
    )
    headers.set(
        "Server-Timing",
        f"{existing}, {measurement}" if existing else measurement,
    )
    return response

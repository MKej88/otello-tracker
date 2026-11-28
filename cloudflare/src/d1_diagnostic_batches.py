"""Bounded read-only D1 requests for the production diagnostic."""
from __future__ import annotations

import json
from time import sleep
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BATCH_SIZE = 6


def query_batches(queries, post, *, batch_size=BATCH_SIZE):
    """Preserve positional results; identify a failed query without leaking its data."""
    if not 1 <= batch_size <= BATCH_SIZE:
        raise ValueError("Invalid diagnostic batch size")
    if any(not q["sql"].lstrip().upper().startswith(("SELECT ", "WITH "))
           for q in queries):
        raise ValueError("Only read-only diagnostic queries are allowed")
    results = []

    def fetch(chunk, offset):
        try:
            response = post(chunk)
            rows = response.get("result")
            if (response.get("success") is not True or not isinstance(rows, list)
                    or len(rows) != len(chunk)
                    or any(row.get("success") is not True for row in rows)):
                raise ValueError("D1 response incomplete or unsuccessful")
            return rows
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            # A rejected multi-query request is retried in smaller groups.
            # Never treat an unavailable result as an empty successful query.
            if len(chunk) > 1 and (not isinstance(exc, HTTPError) or exc.code == 400):
                split = len(chunk) // 2
                return fetch(chunk[:split], offset) + fetch(chunk[split:], offset + split)
            code = f"HTTP {exc.code}" if isinstance(exc, HTTPError) else type(exc).__name__
            raise RuntimeError(
                f"D1-diagnose: spørring {offset + 1}–{offset + len(chunk)} feilet ({code})"
            ) from None

    for offset in range(0, len(queries), batch_size):
        results.extend(fetch(queries[offset:offset + batch_size], offset))
    return {"success": True, "result": results}


def post_d1(url, token, queries):
    payload = json.dumps({"batch": queries}).encode("utf-8")
    request = Request(url, data=payload, method="POST", headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/json", "Content-Type": "application/json",
    })
    for attempt in range(3):
        try:
            with urlopen(request, timeout=30) as response:
                raw = response.read(32 * 1024 * 1024 + 1)
            if len(raw) > 32 * 1024 * 1024:
                raise ValueError("D1 response exceeds diagnostic limit")
            return json.loads(raw)
        except HTTPError as exc:
            if exc.code not in {408, 429, 500, 502, 503, 504} or attempt == 2:
                raise
        except (URLError, TimeoutError):
            if attempt == 2:
                raise
        sleep(2 ** attempt)

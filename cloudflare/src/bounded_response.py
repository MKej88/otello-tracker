from __future__ import annotations

import inspect
from typing import Any


async def _maybe_await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


def _chunk_bytes(value: Any) -> bytes:
    if value is None:
        return b""
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, memoryview):
        return value.tobytes()

    converter = getattr(value, "to_py", None)
    if callable(converter):
        converted = converter()
        if isinstance(converted, memoryview):
            return converted.tobytes()
        if isinstance(converted, (bytes, bytearray)):
            return bytes(converted)
        try:
            return bytes(converted)
        except (TypeError, ValueError):
            pass

    try:
        from js import Uint8Array

        converted = Uint8Array.new(value).to_py()
        if isinstance(converted, memoryview):
            return converted.tobytes()
        return bytes(converted)
    except (ImportError, AttributeError, TypeError, ValueError):
        return bytes(value)


def _declared_content_length(response: Any, *, label: str) -> int | None:
    headers = getattr(response, "headers", None)
    getter = getattr(headers, "get", None)
    raw = getter("content-length") if callable(getter) else None
    if not raw:
        return None
    try:
        declared = int(str(raw))
    except ValueError as exc:
        raise ValueError(f"Ugyldig Content-Length fra {label}") from exc
    if declared < 0:
        raise ValueError(f"Ugyldig Content-Length fra {label}")
    return declared


async def read_response_bytes(response: Any, *, max_bytes: int, label: str) -> bytes:
    """Read a Fetch Response without ever accumulating more than ``max_bytes``.

    Cloudflare/JS responses do not have to include Content-Length. Prefer the
    ReadableStream when available so an oversized chunked response is rejected while it
    is being consumed instead of after ``arrayBuffer()`` has already materialised the
    whole body. The fallback keeps CPython unit-test fakes and older Worker shims working.
    """
    declared = _declared_content_length(response, label=label)
    if declared is not None and declared > max_bytes:
        raise ValueError(f"{label} overstiger Worker-grensen")

    body = getattr(response, "body", None)
    get_reader = getattr(body, "getReader", None)
    if callable(get_reader):
        reader = get_reader()
        chunks: list[bytes] = []
        total = 0
        try:
            while True:
                result = await _maybe_await(reader.read())
                if bool(getattr(result, "done", False)):
                    break
                chunk = _chunk_bytes(getattr(result, "value", None))
                total += len(chunk)
                if total > max_bytes:
                    cancel = getattr(reader, "cancel", None)
                    if callable(cancel):
                        await _maybe_await(cancel("response too large"))
                    raise ValueError(f"{label} overstiger Worker-grensen")
                chunks.append(chunk)
        finally:
            release = getattr(reader, "releaseLock", None)
            if callable(release):
                release()
        return b"".join(chunks)

    array_buffer = getattr(response, "arrayBuffer", None)
    if callable(array_buffer):
        payload = _chunk_bytes(await _maybe_await(array_buffer()))
    else:
        text = getattr(response, "text", None)
        if not callable(text):
            raise TypeError(f"{label} response mangler lesbar body")
        payload = str(await _maybe_await(text())).encode("utf-8")

    if len(payload) > max_bytes:
        raise ValueError(f"{label} overstiger Worker-grensen")
    return payload


async def read_response_text(response: Any, *, max_bytes: int, label: str) -> str:
    return (await read_response_bytes(response, max_bytes=max_bytes, label=label)).decode(
        "utf-8-sig"
    )

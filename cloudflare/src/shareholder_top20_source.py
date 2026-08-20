from __future__ import annotations

from typing import Any, Awaitable, Callable

try:
    from .shareholder_top20_browser import (
        BROWSER_TIMEOUT_MS,
        EXPECTED_ROWS,
        _browser_json,
        _clean_text,
        _row_from_cells,
        _row_from_text,
        parse_rendered_html,
    )
except ImportError:
    from shareholder_top20_browser import (
        BROWSER_TIMEOUT_MS,
        EXPECTED_ROWS,
        _browser_json,
        _clean_text,
        _row_from_cells,
        _row_from_text,
        parse_rendered_html,
    )

EURONEXT_TOP20_URL = "https://ir.oms.no/component/shareholders?lang=en&token=opera"
LEGACY_OMS_URLS = [
    "https://ir.asp.manamind.com/products/html/shareholders.do?key=opera&lang=en",
    "https://ir.asp.manamind.com/products/html/shareholders.do?key=otello&lang=en",
    "https://ir.asp.manamind.com/products/html/shareholders.do?key=opera_irn&lang=en",
    "https://ir.asp.manamind.com/products/html/shareholders.do?key=otello_irn&lang=en",
]
MAX_HTML_CHARS = 750_000


def _normalise_ranks(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(rows) == EXPECTED_ROWS:
        for index, row in enumerate(rows, start=1):
            row["rank"] = index
    return rows


def _tree_cell_names(node: dict[str, Any]) -> list[str]:
    role = str(node.get("role") or "").lower()
    name = _clean_text(node.get("name") or "")
    if role in {"cell", "gridcell", "rowheader", "columnheader"} and name:
        return [name]
    values: list[str] = []
    for child in node.get("children") or []:
        if isinstance(child, dict):
            values.extend(_tree_cell_names(child))
    return values


def parse_accessibility_tree(payload: dict[str, Any]) -> list[dict[str, Any]]:
    root = payload.get("accessibilityTree") if "accessibilityTree" in payload else payload
    if not isinstance(root, dict):
        return []

    rows: list[dict[str, Any]] = []

    def visit(node: dict[str, Any]) -> None:
        if len(rows) >= EXPECTED_ROWS:
            return
        role = str(node.get("role") or "").lower()
        if role == "row":
            cells = _tree_cell_names(node)
            fallback = _clean_text(node.get("name") or " ".join(cells))
            row = _row_from_cells(cells, fallback, default_rank=len(rows) + 1)
            if row is None and fallback:
                row = _row_from_text(fallback, default_rank=len(rows) + 1)
            if row is not None:
                rows.append(row)
                return
        for child in node.get("children") or []:
            if isinstance(child, dict):
                visit(child)

    visit(root)
    return _normalise_ranks(rows)


def parse_markdown(markdown: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw_line in (markdown or "").splitlines():
        line = _clean_text(raw_line)
        if not line:
            continue
        row = None
        if "|" in line:
            cells = [_clean_text(part) for part in line.strip("|").split("|")]
            separator = cells and all(not cell or set(cell) <= {"-", ":", " "} for cell in cells)
            if cells and not separator:
                row = _row_from_cells(cells, line, default_rank=len(rows) + 1)
        if row is None:
            row = _row_from_text(line, default_rank=len(rows) + 1)
        if row is not None:
            rows.append(row)
        if len(rows) == EXPECTED_ROWS:
            break
    return _normalise_ranks(rows)


async def _legacy_html_rows(
    *,
    fetcher: Callable[..., Awaitable[Any]],
) -> tuple[list[dict[str, Any]], str | None, list[dict[str, Any]]]:
    diagnostics: list[dict[str, Any]] = []
    for url in LEGACY_OMS_URLS:
        try:
            response = await fetcher(
                url,
                headers={
                    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                    "User-Agent": "otello-tracker/1.0 private-investor-dashboard",
                },
                redirect="follow",
            )
            status = int(getattr(response, "status", 0) or 0)
            if not bool(getattr(response, "ok", False)):
                diagnostics.append({"url": url, "status": status, "rows": 0})
                continue
            html = str(await response.text())[:MAX_HTML_CHARS]
            rows = parse_rendered_html(html)
            diagnostics.append({"url": url, "status": status, "rows": len(rows)})
            if len(rows) == EXPECTED_ROWS:
                return rows, url, diagnostics
        except Exception as exc:
            diagnostics.append({"url": url, "error": type(exc).__name__, "rows": 0})
    return [], None, diagnostics


async def fetch_top20(
    browser: Any,
    *,
    fetcher: Callable[..., Awaitable[Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if fetcher is None:
        from workers import fetch

        fetcher = fetch

    legacy_rows, legacy_url, legacy_diagnostics = await _legacy_html_rows(fetcher=fetcher)
    if len(legacy_rows) == EXPECTED_ROWS:
        return legacy_rows, {
            "method": "OMS_LEGACY_STATIC_HTML",
            "browser_ms": 0,
            "browser_calls": 0,
            "extraction_url": legacy_url,
            "legacy_attempts": legacy_diagnostics,
        }

    from js import Object
    from pyodide.ffi import to_js as _to_js

    def to_js(value: Any):
        return _to_js(value, dict_converter=Object.fromEntries)

    snapshot_response = await browser.quickAction(
        "snapshot",
        to_js(
            {
                "url": EURONEXT_TOP20_URL,
                "formats": ["content", "markdown", "accessibilityTree"],
                "gotoOptions": {"waitUntil": "networkidle2", "timeout": BROWSER_TIMEOUT_MS},
            }
        ),
    )
    payload, browser_ms = await _browser_json(snapshot_response)
    result = payload.get("result") or {}
    if not isinstance(result, dict):
        result = {}

    content = str(result.get("content") or "")
    content_rows = parse_rendered_html(content)
    if len(content_rows) == EXPECTED_ROWS:
        return content_rows, {
            "method": "BROWSER_RUN_SNAPSHOT_HTML",
            "browser_ms": browser_ms,
            "browser_calls": 1,
            "legacy_attempts": legacy_diagnostics,
        }

    tree = result.get("accessibilityTree") or {}
    tree_rows = parse_accessibility_tree(tree if isinstance(tree, dict) else {})
    if len(tree_rows) == EXPECTED_ROWS:
        return tree_rows, {
            "method": "BROWSER_RUN_ACCESSIBILITY_TREE",
            "browser_ms": browser_ms,
            "browser_calls": 1,
            "legacy_attempts": legacy_diagnostics,
        }

    markdown = str(result.get("markdown") or "")
    markdown_rows = parse_markdown(markdown)
    if len(markdown_rows) == EXPECTED_ROWS:
        return markdown_rows, {
            "method": "BROWSER_RUN_MARKDOWN",
            "browser_ms": browser_ms,
            "browser_calls": 1,
            "legacy_attempts": legacy_diagnostics,
        }

    meta = payload.get("meta") or {}
    title = _clean_text(meta.get("title") or "") if isinstance(meta, dict) else ""
    markdown_hint = _clean_text(markdown)[:220]
    content_hint = _clean_text(content)[:220]
    raise RuntimeError(
        "Euronext Top 20 kunne ikke leses. "
        f"legacy={legacy_diagnostics}; html_rows={len(content_rows)}; "
        f"tree_rows={len(tree_rows)}; markdown_rows={len(markdown_rows)}; "
        f"title={title!r}; markdown_hint={markdown_hint!r}; content_hint={content_hint!r}"
    )

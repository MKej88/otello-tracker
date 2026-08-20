from __future__ import annotations

import html as html_lib
import json
import re
from typing import Any, Awaitable, Callable
from urllib.parse import urlsplit

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
MAX_NETWORK_BODY_CHARS = 350_000
MAX_NETWORK_CANDIDATES = 12
NETWORK_PROBE_WAIT_MS = 6_000


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


def _first_key(record: dict[str, Any], aliases: tuple[str, ...]) -> tuple[str | None, Any]:
    lowered = {str(key).lower().replace("_", "").replace("-", ""): key for key in record}
    for alias in aliases:
        normalized = alias.lower().replace("_", "").replace("-", "")
        key = lowered.get(normalized)
        if key is not None:
            return str(key), record[key]
    return None, None


def _json_shares(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        parsed = int(value)
        return parsed if parsed > 0 else None
    text = _clean_text(str(value))
    digits = re.sub(r"[^0-9]", "", text.split(".", 1)[0] if text.endswith(".00") else text)
    if not digits:
        return None
    parsed = int(digits)
    return parsed if parsed > 0 else None


def _json_pct(key: str | None, value: Any) -> str | None:
    if value is None:
        return None
    try:
        if isinstance(value, str):
            raw = _clean_text(value).replace("%", "").replace(",", ".")
            number = float(raw)
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            number = float(value)
        else:
            return None
    except ValueError:
        return None
    normalized_key = (key or "").lower()
    if 0 < number <= 1 and any(token in normalized_key for token in ("ratio", "fraction")):
        number *= 100
    if number < 0 or number > 100:
        return None
    return f"{number:.6f}".rstrip("0").rstrip(".")


def _json_row(record: dict[str, Any], default_rank: int) -> dict[str, Any] | None:
    name_key, name_value = _first_key(
        record,
        (
            "shareholder_name",
            "shareholderName",
            "shareholder",
            "ownerName",
            "owner",
            "investorName",
            "investor",
            "name",
            "accountName",
        ),
    )
    shares_key, shares_value = _first_key(
        record,
        (
            "shares",
            "numberOfShares",
            "number_of_shares",
            "shareCount",
            "share_count",
            "quantity",
            "holding",
            "holdings",
            "amount",
        ),
    )
    if name_key is None or shares_key is None:
        return None
    name = _clean_text(str(name_value or ""))
    shares = _json_shares(shares_value)
    if len(name) < 2 or shares is None:
        return None

    rank_key, rank_value = _first_key(record, ("rank", "position", "place", "no", "number"))
    try:
        rank = int(rank_value) if rank_key is not None else default_rank
    except (TypeError, ValueError):
        rank = default_rank

    pct_key, pct_value = _first_key(
        record,
        (
            "ownershipPct",
            "ownership_pct",
            "ownershipPercent",
            "ownershipPercentage",
            "percentage",
            "percent",
            "pct",
            "sharePct",
            "sharePercentage",
            "ratio",
        ),
    )
    _, country = _first_key(record, ("country", "countryCode", "country_code", "nation"))
    _, account_type = _first_key(record, ("accountType", "account_type", "type", "account"))

    return {
        "rank": rank,
        "shareholder_name": name,
        "country": _clean_text(str(country or "")) or None,
        "shares": shares,
        "ownership_pct": _json_pct(pct_key, pct_value),
        "account_type": _clean_text(str(account_type or "")) or None,
    }


def parse_json_payload(payload: Any) -> list[dict[str, Any]]:
    best: list[dict[str, Any]] = []

    def visit(value: Any) -> None:
        nonlocal best
        if len(best) == EXPECTED_ROWS:
            return
        if isinstance(value, list):
            candidate: list[dict[str, Any]] = []
            for item in value:
                if isinstance(item, dict):
                    row = _json_row(item, len(candidate) + 1)
                    if row is not None:
                        candidate.append(row)
            if len(candidate) >= EXPECTED_ROWS:
                best = _normalise_ranks(candidate[:EXPECTED_ROWS])
                return
            if len(candidate) > len(best):
                best = candidate
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            for item in value.values():
                visit(item)

    visit(payload)
    return _normalise_ranks(best) if len(best) == EXPECTED_ROWS else best


def parse_network_body(body: str) -> list[dict[str, Any]]:
    text = (body or "").strip()
    if not text:
        return []
    if text.startswith(("{", "[")):
        try:
            rows = parse_json_payload(json.loads(text))
            if len(rows) == EXPECTED_ROWS:
                return rows
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    rows = parse_rendered_html(text)
    if len(rows) == EXPECTED_ROWS:
        return rows
    rows = parse_markdown(text)
    return rows if len(rows) == EXPECTED_ROWS else []


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


def _extract_probe_payload(content: str) -> dict[str, Any]:
    match = re.search(
        r'<script[^>]+id=["\']otello-network-dump["\'][^>]*>(.*?)</script>',
        content or "",
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return {}
    raw = html_lib.unescape(match.group(1)).strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _candidate_resource_urls(probe: dict[str, Any]) -> list[str]:
    scored: list[tuple[int, str]] = []
    seen: set[str] = set()
    for item in probe.get("resources") or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or item.get("name") or "").strip()
        initiator = str(item.get("type") or item.get("initiatorType") or "").lower()
        if not url.startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        lowered = url.lower()
        path = urlsplit(url).path.lower()
        if any(path.endswith(ext) for ext in (".js", ".css", ".png", ".jpg", ".jpeg", ".svg", ".woff", ".woff2", ".ico")):
            continue
        score = 0
        if initiator in {"fetch", "xmlhttprequest", "xhr"}:
            score += 100
        for token in ("shareholder", "holder", "owner", "ownership", "investor", "component", "api", "graphql", "oms", "infront"):
            if token in lowered:
                score += 10
        if score:
            scored.append((score, url))
    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    return [url for _, url in scored[:MAX_NETWORK_CANDIDATES]]


async def _browser_network_probe(browser: Any, to_js: Callable[[Any], Any]) -> tuple[dict[str, Any], int | None]:
    probe_script = r"""
(() => {
  const done = async () => {
    const resources = performance.getEntriesByType('resource').map((entry) => ({
      url: entry.name,
      type: entry.initiatorType || ''
    }));
    const scripts = Array.from(document.scripts).map((script) => script.src).filter(Boolean);
    const candidates = resources
      .filter((entry) => ['fetch', 'xmlhttprequest'].includes(String(entry.type).toLowerCase()))
      .map((entry) => entry.url)
      .filter((url, index, all) => all.indexOf(url) === index)
      .slice(0, 12);
    const responses = [];
    for (const url of candidates) {
      try {
        const response = await fetch(url, { credentials: 'include' });
        const body = (await response.text()).slice(0, 350000);
        responses.push({
          url,
          status: response.status,
          contentType: response.headers.get('content-type') || '',
          body
        });
      } catch (error) {
        responses.push({ url, error: String(error) });
      }
    }
    const payload = {
      href: location.href,
      resources,
      scripts,
      responses
    };
    let node = document.getElementById('otello-network-dump');
    if (!node) {
      node = document.createElement('script');
      node.id = 'otello-network-dump';
      node.type = 'application/json';
      document.head.appendChild(node);
    }
    node.textContent = JSON.stringify(payload).replace(/<\//g, '<\\/');
  };
  done();
})();
"""
    response = await browser.quickAction(
        "content",
        to_js(
            {
                "url": EURONEXT_TOP20_URL,
                "gotoOptions": {"waitUntil": "networkidle2", "timeout": BROWSER_TIMEOUT_MS},
                "addScriptTag": [{"content": probe_script}],
                "waitForTimeout": NETWORK_PROBE_WAIT_MS,
                "actionTimeout": 30_000,
            }
        ),
    )
    payload, browser_ms = await _browser_json(response)
    content = str(payload.get("result") or "")
    return _extract_probe_payload(content), browser_ms


async def _network_probe_rows(
    browser: Any,
    *,
    to_js: Callable[[Any], Any],
    fetcher: Callable[..., Awaitable[Any]],
) -> tuple[list[dict[str, Any]], str | None, dict[str, Any]]:
    probe, browser_ms = await _browser_network_probe(browser, to_js)
    diagnostics: dict[str, Any] = {
        "browser_ms": browser_ms,
        "resource_count": len(probe.get("resources") or []),
        "script_count": len(probe.get("scripts") or []),
        "candidate_urls": [],
        "browser_refetch": [],
        "worker_fetch": [],
    }

    for response in probe.get("responses") or []:
        if not isinstance(response, dict):
            continue
        url = str(response.get("url") or "")
        body = str(response.get("body") or "")[:MAX_NETWORK_BODY_CHARS]
        rows = parse_network_body(body)
        diagnostics["browser_refetch"].append(
            {
                "url": url,
                "status": response.get("status"),
                "content_type": response.get("contentType"),
                "rows": len(rows),
                "error": response.get("error"),
            }
        )
        if len(rows) == EXPECTED_ROWS:
            return rows, url, diagnostics

    candidates = _candidate_resource_urls(probe)
    diagnostics["candidate_urls"] = candidates
    for url in candidates:
        try:
            response = await fetcher(
                url,
                headers={
                    "Accept": "application/json,text/plain,text/html,*/*;q=0.8",
                    "Referer": EURONEXT_TOP20_URL,
                    "User-Agent": "otello-tracker/1.0 private-investor-dashboard",
                },
                redirect="follow",
            )
            status = int(getattr(response, "status", 0) or 0)
            if not bool(getattr(response, "ok", False)):
                diagnostics["worker_fetch"].append({"url": url, "status": status, "rows": 0})
                continue
            body = str(await response.text())[:MAX_NETWORK_BODY_CHARS]
            rows = parse_network_body(body)
            diagnostics["worker_fetch"].append({"url": url, "status": status, "rows": len(rows)})
            if len(rows) == EXPECTED_ROWS:
                return rows, url, diagnostics
        except Exception as exc:
            diagnostics["worker_fetch"].append(
                {"url": url, "error": type(exc).__name__, "rows": 0}
            )
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

    network_rows, network_url, network_diagnostics = await _network_probe_rows(
        browser,
        to_js=to_js,
        fetcher=fetcher,
    )
    if len(network_rows) == EXPECTED_ROWS:
        return network_rows, {
            "method": "OMS_NETWORK_SOURCE",
            "browser_ms": (browser_ms or 0) + int(network_diagnostics.get("browser_ms") or 0),
            "browser_calls": 2,
            "extraction_url": network_url,
            "legacy_attempts": legacy_diagnostics,
            "network_probe": network_diagnostics,
        }

    meta = payload.get("meta") or {}
    title = _clean_text(meta.get("title") or "") if isinstance(meta, dict) else ""
    markdown_hint = _clean_text(markdown)[:220]
    content_hint = _clean_text(content)[:220]
    raise RuntimeError(
        "Euronext Top 20 kunne ikke leses. "
        f"legacy={legacy_diagnostics}; html_rows={len(content_rows)}; "
        f"tree_rows={len(tree_rows)}; markdown_rows={len(markdown_rows)}; "
        f"network={network_diagnostics}; "
        f"title={title!r}; markdown_hint={markdown_hint!r}; content_hint={content_hint!r}"
    )

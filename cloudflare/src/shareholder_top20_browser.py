from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from typing import Any

EURONEXT_TOP20_URL = "https://ir.oms.no/component/shareholders?lang=en&token=opera"
EXPECTED_ROWS = 20
MAX_BROWSER_CALLS = 2
BROWSER_TIMEOUT_MS = 30_000


class _CellParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.cells: list[str] = []
        self._depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {name.lower(): value for name, value in attrs}
        is_cell = tag.lower() in {"td", "th"} or attr.get("role") in {
            "cell",
            "gridcell",
            "columnheader",
        }
        if is_cell:
            if self._depth == 0:
                self._parts = []
            self._depth += 1
        elif self._depth:
            self._depth += 1

    def handle_endtag(self, tag: str) -> None:
        if not self._depth:
            return
        self._depth -= 1
        if self._depth == 0:
            value = _clean_text(" ".join(self._parts))
            if value:
                self.cells.append(value)
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._depth:
            self._parts.append(data)


class _RenderedRowParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._row_depth = 0
        self._row_html: list[str] = []
        self._row_text: list[str] = []
        self.rows: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {name.lower(): value for name, value in attrs}
        is_row = tag.lower() == "tr" or attr.get("role") == "row"
        if is_row and self._row_depth == 0:
            self._row_depth = 1
            self._row_html = []
            self._row_text = []
            return
        if self._row_depth:
            self._row_depth += 1
            attrs_text = "".join(f' {name}="{value or ""}"' for name, value in attrs)
            self._row_html.append(f"<{tag}{attrs_text}>")

    def handle_endtag(self, tag: str) -> None:
        if not self._row_depth:
            return
        self._row_depth -= 1
        if self._row_depth == 0:
            self.rows.append(("".join(self._row_html), _clean_text(" ".join(self._row_text))))
            self._row_html = []
            self._row_text = []
        else:
            self._row_html.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if self._row_depth:
            self._row_text.append(data)
            self._row_html.append(data)


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value).replace("\u00a0", " ")).strip()


def _parse_rank(value: str) -> int | None:
    match = re.fullmatch(r"\s*(\d{1,2})[.)]?\s*", value)
    if not match:
        return None
    rank = int(match.group(1))
    return rank if 1 <= rank <= EXPECTED_ROWS else None


def _parse_shares(value: str) -> int | None:
    clean = _clean_text(value)
    if not re.fullmatch(r"(?:\d{4,}|\d{1,3}(?:[ .,'’]\d{3})+)(?:\.00)?", clean):
        return None
    integer_part = clean[:-3] if clean.endswith(".00") else clean
    digits = re.sub(r"[^0-9]", "", integer_part)
    return int(digits) if digits else None


def _parse_pct(value: str) -> float | None:
    clean = _clean_text(value).replace(" ", "")
    match = re.fullmatch(r"(\d{1,3}(?:[.,]\d+)?)%?", clean)
    if not match:
        return None
    # A bare integer with 4+ digits is a share count, never a percentage.
    if "%" not in clean and "," not in clean and "." not in clean:
        return None
    return float(match.group(1).replace(",", "."))


def _pct_text(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _cells_from_html(html: str) -> list[str]:
    parser = _CellParser()
    parser.feed(html or "")
    parser.close()
    return parser.cells


def _row_from_cells(
    cells: list[str],
    fallback_text: str,
    *,
    default_rank: int,
) -> dict[str, Any] | None:
    values = [_clean_text(item) for item in cells if _clean_text(item)]
    if not values:
        return None

    explicit_rank = _parse_rank(values[0])
    start = 1 if explicit_rank is not None else 0
    rank = explicit_rank or default_rank

    share_index = next(
        (index for index in range(start, len(values)) if _parse_shares(values[index]) is not None),
        None,
    )
    if share_index is None:
        return _row_from_text(fallback_text, default_rank=rank)

    shares = _parse_shares(values[share_index])
    before_shares = values[start:share_index]
    if not before_shares or shares is None:
        return _row_from_text(fallback_text, default_rank=rank)

    name = _clean_text(" ".join(before_shares))
    if name.lower().startswith("total number") or name.lower().startswith("total shares"):
        return None

    pct_indices = [
        index for index in range(share_index + 1, len(values)) if _parse_pct(values[index]) is not None
    ]
    # OMS commonly exposes two percentages: share of Top 20 and share of total capital.
    # The investor dashboard wants the latter, so use the last percentage column.
    ownership_pct = _parse_pct(values[pct_indices[-1]]) if pct_indices else None
    after_pct = pct_indices[-1] if pct_indices else share_index
    trailing = [
        value
        for index, value in enumerate(values)
        if index > after_pct and _parse_shares(value) is None and _parse_pct(value) is None
    ]

    account_type = None
    country = None
    if len(trailing) >= 2:
        account_type = trailing[0]
        country = trailing[-1]
    elif len(trailing) == 1:
        token = trailing[0]
        if re.fullmatch(r"[A-Z]{2,3}", token):
            country = token
        else:
            account_type = token

    return {
        "rank": rank,
        "shareholder_name": name,
        "country": country,
        "shares": shares,
        "ownership_pct": None if ownership_pct is None else _pct_text(ownership_pct),
        "account_type": account_type,
    }


def _row_from_text(text: str, *, default_rank: int) -> dict[str, Any] | None:
    clean = _clean_text(text)
    # Text fallback deliberately anchors on the share count. Everything before it is name;
    # percentages/account/country are best-effort because cell structure is no longer available.
    share_match = re.search(r"(?:^|\s)(\d{4,}|\d{1,3}(?:[ .,'’]\d{3})+)(?:\.00)?(?:\s|$)", clean)
    if not share_match:
        return None
    prefix = _clean_text(clean[: share_match.start()])
    explicit = re.match(r"^(\d{1,2})[.)]?\s+(.+)$", prefix)
    rank = default_rank
    name = prefix
    if explicit and _parse_rank(explicit.group(1)) is not None:
        rank = int(explicit.group(1))
        name = _clean_text(explicit.group(2))
    if not name or name.lower().startswith("total number"):
        return None
    shares = _parse_shares(share_match.group(1))
    if shares is None:
        return None
    suffix = clean[share_match.end() :]
    pcts = [_parse_pct(value) for value in re.findall(r"\d{1,3}(?:[.,]\d+)?%", suffix)]
    pcts = [value for value in pcts if value is not None]
    return {
        "rank": rank,
        "shareholder_name": name,
        "country": None,
        "shares": shares,
        "ownership_pct": None if not pcts else _pct_text(pcts[-1]),
        "account_type": None,
    }


def _parse_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in items:
        row = _row_from_cells(
            _cells_from_html(str(item.get("html") or "")),
            str(item.get("text") or ""),
            default_rank=len(rows) + 1,
        )
        if row is not None:
            row["rank"] = len(rows) + 1 if _parse_rank(str(row.get("rank"))) is None else int(row["rank"])
            rows.append(row)
        if len(rows) == EXPECTED_ROWS:
            break
    if len(rows) == EXPECTED_ROWS:
        # OMS may expose explicit rank or no rank at all. Preserve visual order as the source of truth.
        for index, row in enumerate(rows, start=1):
            row["rank"] = index
    return rows


def parse_scrape_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if not payload.get("success"):
        raise ValueError("Browser Run returnerte success=false")
    best: list[dict[str, Any]] = []
    for group in payload.get("result") or []:
        rows = _parse_items(list(group.get("results") or []))
        if len(rows) == EXPECTED_ROWS:
            return rows
        if len(rows) > len(best):
            best = rows
    return best


def parse_rendered_html(html: str) -> list[dict[str, Any]]:
    parser = _RenderedRowParser()
    parser.feed(html or "")
    parser.close()
    items = [{"html": row_html, "text": row_text} for row_html, row_text in parser.rows]
    return _parse_items(items)


async def _browser_json(response: Any) -> tuple[dict[str, Any], int | None]:
    status = int(getattr(response, "status", 0) or 0)
    if not bool(getattr(response, "ok", False)):
        detail = str(await response.text())[:500]
        raise RuntimeError(f"Browser Run feilet med HTTP {status or 'unknown'}: {detail}")
    body = str(await response.text())
    browser_ms = None
    try:
        raw_ms = response.headers.get("X-Browser-Ms-Used")
        browser_ms = int(str(raw_ms)) if raw_ms is not None else None
    except (TypeError, ValueError):
        browser_ms = None
    return json.loads(body), browser_ms


async def fetch_top20(browser: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from js import Object
    from pyodide.ffi import to_js as _to_js

    def to_js(value: Any):
        return _to_js(value, dict_converter=Object.fromEntries)

    scrape_response = await browser.quickAction(
        "scrape",
        to_js(
            {
                "url": EURONEXT_TOP20_URL,
                "elements": [
                    {"selector": "table tbody tr"},
                    {"selector": "table tr"},
                    {"selector": "[role='row']"},
                    {"selector": "tr"},
                ],
                "gotoOptions": {"waitUntil": "networkidle2", "timeout": BROWSER_TIMEOUT_MS},
            }
        ),
    )
    payload, browser_ms = await _browser_json(scrape_response)
    rows = parse_scrape_payload(payload)
    if len(rows) == EXPECTED_ROWS:
        return rows, {
            "method": "BROWSER_RUN_SCRAPE",
            "browser_ms": browser_ms,
            "browser_calls": 1,
        }

    content_response = await browser.quickAction(
        "content",
        to_js(
            {
                "url": EURONEXT_TOP20_URL,
                "gotoOptions": {"waitUntil": "networkidle2", "timeout": BROWSER_TIMEOUT_MS},
            }
        ),
    )
    content_payload, fallback_ms = await _browser_json(content_response)
    fallback_rows = parse_rendered_html(str(content_payload.get("result") or ""))
    return fallback_rows, {
        "method": "BROWSER_RUN_CONTENT_FALLBACK",
        "browser_ms": (browser_ms or 0) + (fallback_ms or 0),
        "browser_calls": MAX_BROWSER_CALLS,
    }

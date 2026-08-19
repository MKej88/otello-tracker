from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any

try:
    from .r2_archive import archive_bytes
except ImportError:
    from r2_archive import archive_bytes

EURONEXT_TOP20_URL = "https://ir.oms.no/component/shareholders?lang=en&token=opera"
SOURCE_KIND = "EURONEXT_OMS"
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
        is_cell = tag.lower() in {"td", "th"} or attr.get("role") in {"cell", "gridcell", "columnheader"}
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
    if not re.fullmatch(r"(?:\d{4,}|\d{1,3}(?:[ .,'’]\d{3})+)", clean):
        return None
    digits = re.sub(r"[^0-9]", "", clean)
    return int(digits) if digits else None


def _parse_pct(value: str) -> float | None:
    clean = _clean_text(value).replace(" ", "")
    match = re.fullmatch(r"(\d{1,3}(?:[.,]\d+)?)%", clean)
    if not match:
        return None
    return float(match.group(1).replace(",", "."))


def _cells_from_html(html: str) -> list[str]:
    parser = _CellParser()
    parser.feed(html or "")
    parser.close()
    return parser.cells


def _row_from_cells(cells: list[str], fallback_text: str = "") -> dict[str, Any] | None:
    values = [_clean_text(item) for item in cells if _clean_text(item)]
    rank_index = next((index for index, value in enumerate(values) if _parse_rank(value) is not None), None)
    if rank_index is None:
        return _row_from_text(fallback_text)

    rank = _parse_rank(values[rank_index])
    share_index = next(
        (index for index in range(rank_index + 1, len(values)) if _parse_shares(values[index]) is not None),
        None,
    )
    if rank is None or share_index is None:
        return _row_from_text(fallback_text)

    shares = _parse_shares(values[share_index])
    pct_index = next(
        (index for index in range(share_index + 1, len(values)) if _parse_pct(values[index]) is not None),
        None,
    )

    text_cells = [
        value
        for index, value in enumerate(values[rank_index + 1 : share_index], start=rank_index + 1)
        if _parse_shares(value) is None and _parse_pct(value) is None
    ]
    if not text_cells:
        return _row_from_text(fallback_text)

    name = text_cells[0]
    country = text_cells[1] if len(text_cells) >= 2 and len(text_cells[1]) <= 32 else None
    trailing = [
        value
        for index, value in enumerate(values)
        if index > (pct_index if pct_index is not None else share_index)
        and _parse_shares(value) is None
        and _parse_pct(value) is None
    ]
    account_type = trailing[0] if trailing else None
    pct = _parse_pct(values[pct_index]) if pct_index is not None else None

    return {
        "rank": rank,
        "shareholder_name": name,
        "country": country,
        "shares": shares,
        "ownership_pct": None if pct is None else _pct_text(pct),
        "account_type": account_type,
    }


def _row_from_text(text: str) -> dict[str, Any] | None:
    clean = _clean_text(text)
    match = re.match(
        r"^(\d{1,2})[.)]?\s+(.+?)\s+(\d{4,}|\d{1,3}(?:[ .,'’]\d{3})+)\s+(\d{1,3}(?:[.,]\d+)?%)\s*$",
        clean,
    )
    if not match:
        return None
    rank = _parse_rank(match.group(1))
    shares = _parse_shares(match.group(3))
    pct = _parse_pct(match.group(4))
    if rank is None or shares is None:
        return None
    return {
        "rank": rank,
        "shareholder_name": _clean_text(match.group(2)),
        "country": None,
        "shares": shares,
        "ownership_pct": None if pct is None else _pct_text(pct),
        "account_type": None,
    }


def _pct_text(value: float) -> str:
    return (f"{value:.6f}").rstrip("0").rstrip(".")


def parse_scrape_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if not payload.get("success"):
        raise ValueError("Browser Run returnerte success=false")
    groups = payload.get("result") or []
    candidates: dict[int, dict[str, Any]] = {}
    for group in groups:
        for item in group.get("results") or []:
            row = _row_from_cells(_cells_from_html(str(item.get("html") or "")), str(item.get("text") or ""))
            if row is not None:
                candidates[int(row["rank"])] = row
    return [candidates[rank] for rank in sorted(candidates)]


def validate_rows(rows: list[dict[str, Any]], *, total_issued_shares: int | None = None) -> list[dict[str, Any]]:
    if len(rows) != EXPECTED_ROWS:
        raise ValueError(f"Forventet {EXPECTED_ROWS} Top 20-rader, fant {len(rows)}")
    ranks = [int(row["rank"]) for row in rows]
    if ranks != list(range(1, EXPECTED_ROWS + 1)):
        raise ValueError(f"Ugyldig rangering: {ranks}")
    names = [_clean_text(row["shareholder_name"]) for row in rows]
    if any(len(name) < 2 for name in names) or len(set(name.casefold() for name in names)) != EXPECTED_ROWS:
        raise ValueError("Aksjonærnavn mangler eller er duplisert")
    shares = [int(row["shares"]) for row in rows]
    if any(value <= 0 for value in shares):
        raise ValueError("Alle Top 20-rader må ha positivt aksjetall")
    if total_issued_shares and sum(shares) > int(total_issued_shares):
        raise ValueError("Top 20-summen overstiger totalt utstedte aksjer")
    pct_values = [float(row["ownership_pct"]) for row in rows if row.get("ownership_pct") is not None]
    if any(value < 0 or value > 100 for value in pct_values) or sum(pct_values) > 100.5:
        raise ValueError("Ugyldige eierandeler i Top 20-listen")
    return rows


def canonical_rows(rows: list[dict[str, Any]]) -> bytes:
    normalized = [
        {
            "rank": int(row["rank"]),
            "shareholder_name": _clean_text(row["shareholder_name"]),
            "country": _clean_text(row.get("country") or "") or None,
            "shares": int(row["shares"]),
            "ownership_pct": str(row.get("ownership_pct") or "") or None,
            "account_type": _clean_text(row.get("account_type") or "") or None,
        }
        for row in rows
    ]
    return (json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


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
        return rows, {"method": "BROWSER_RUN_SCRAPE", "browser_ms": browser_ms, "browser_calls": 1}

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
    html = str(content_payload.get("result") or "")
    fallback_rows = parse_rendered_html(html)
    return fallback_rows, {
        "method": "BROWSER_RUN_CONTENT_FALLBACK",
        "browser_ms": (browser_ms or 0) + (fallback_ms or 0),
        "browser_calls": MAX_BROWSER_CALLS,
    }


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


def parse_rendered_html(html: str) -> list[dict[str, Any]]:
    parser = _RenderedRowParser()
    parser.feed(html or "")
    parser.close()
    candidates: dict[int, dict[str, Any]] = {}
    for row_html, row_text in parser.rows:
        row = _row_from_cells(_cells_from_html(row_html), row_text)
        if row is not None:
            candidates[int(row["rank"])] = row
    return [candidates[rank] for rank in sorted(candidates)]


async def _latest_share_count(repository: Any) -> dict[str, Any] | None:
    return await repository.first(
        """
        SELECT total_shares, treasury_shares, outstanding_shares
        FROM otello_share_counts
        ORDER BY effective_from DESC, id DESC
        LIMIT 1
        """
    )


async def _latest_snapshot_rows(repository: Any) -> list[dict[str, Any]]:
    return await repository.all(
        """
        SELECT sr.rank, sr.shareholder_name, sr.country, sr.shares, sr.ownership_pct, sr.account_type
        FROM shareholder_snapshot_rows sr
        JOIN shareholder_snapshots ss ON ss.id = sr.snapshot_id
        WHERE ss.source_kind = ?
        ORDER BY ss.snapshot_date DESC, ss.id DESC, sr.rank ASC
        LIMIT 20
        """,
        (SOURCE_KIND,),
    )


async def store_snapshot(
    repository: Any,
    rows: list[dict[str, Any]],
    *,
    snapshot_date: str,
    archive_bucket: Any | None,
    browser_metadata: dict[str, Any],
) -> dict[str, Any]:
    share_count = await _latest_share_count(repository)
    total_issued = int(share_count["total_shares"]) if share_count and share_count.get("total_shares") else None
    rows = validate_rows(rows, total_issued_shares=total_issued)
    canonical = canonical_rows(rows)
    content_hash = hashlib.sha256(canonical).hexdigest()

    previous = await _latest_snapshot_rows(repository)
    if len(previous) == EXPECTED_ROWS and hashlib.sha256(canonical_rows(previous)).hexdigest() == content_hash:
        return {
            "status": "unchanged",
            "snapshot_date": snapshot_date,
            "rows": EXPECTED_ROWS,
            "content_sha256": content_hash,
            **browser_metadata,
        }

    archived = None
    if archive_bucket is not None:
        archived = await archive_bytes(
            archive_bucket,
            canonical,
            source="euronext",
            kind="otec-shareholders-top20",
            logical_date=snapshot_date,
            filename=f"otec-top20-{snapshot_date}.json",
        )

    document_id = await repository.create_source_document(
        source_code="EURONEXT",
        external_id=f"otec-top20:{snapshot_date}",
        document_type="SHAREHOLDER_LIST",
        title=f"Otello Top 20 shareholders {snapshot_date}",
        url=EURONEXT_TOP20_URL,
        published_at=f"{snapshot_date}T23:59:59Z",
        content_sha256=content_hash,
        metadata={
            "provider": "Euronext OMS",
            "extraction_method": browser_metadata.get("method"),
            "browser_ms": browser_metadata.get("browser_ms"),
            "browser_calls": browser_metadata.get("browser_calls"),
            "row_count": EXPECTED_ROWS,
            "permission_basis": "PROJECT_OWNER_CONFIRMED_PERMISSION_2026-08-19",
            "r2_key": archived.get("r2_key") if archived else None,
        },
    )

    existing = await repository.first(
        "SELECT id FROM shareholder_snapshots WHERE snapshot_date=? AND source_kind=? LIMIT 1",
        (snapshot_date, SOURCE_KIND),
    )
    if existing is not None:
        await repository.run("DELETE FROM shareholder_snapshots WHERE id=?", (int(existing["id"]),))

    notes = json.dumps(
        {
            "content_sha256": content_hash,
            "source_document_id": document_id,
            "r2_key": archived.get("r2_key") if archived else None,
            **browser_metadata,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    await repository.run(
        """
        INSERT INTO shareholder_snapshots(
            snapshot_date, source_url, source_kind, total_issued_shares,
            treasury_shares, outstanding_shares, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            snapshot_date,
            EURONEXT_TOP20_URL,
            SOURCE_KIND,
            total_issued,
            int(share_count["treasury_shares"]) if share_count and share_count.get("treasury_shares") is not None else None,
            int(share_count["outstanding_shares"]) if share_count and share_count.get("outstanding_shares") is not None else None,
            notes,
        ),
    )
    snapshot = await repository.first(
        "SELECT id FROM shareholder_snapshots WHERE snapshot_date=? AND source_kind=? LIMIT 1",
        (snapshot_date, SOURCE_KIND),
    )
    if snapshot is None:
        raise RuntimeError("Snapshot ble skrevet, men kunne ikke leses tilbake")
    snapshot_id = int(snapshot["id"])

    try:
        statements = []
        sql = """
            INSERT INTO shareholder_snapshot_rows(
                snapshot_id, rank, shareholder_name, country, shares, ownership_pct, account_type
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        for row in rows:
            statements.append(
                repository.database.prepare(sql).bind(
                    snapshot_id,
                    int(row["rank"]),
                    str(row["shareholder_name"]),
                    row.get("country"),
                    int(row["shares"]),
                    row.get("ownership_pct"),
                    row.get("account_type"),
                )
            )
        await repository.database.batch(statements)
    except Exception:
        await repository.run("DELETE FROM shareholder_snapshots WHERE id=?", (snapshot_id,))
        raise

    return {
        "status": "stored",
        "snapshot_id": snapshot_id,
        "snapshot_date": snapshot_date,
        "rows": EXPECTED_ROWS,
        "content_sha256": content_hash,
        "source_document_id": document_id,
        "r2_archive": archived,
        **browser_metadata,
    }


async def refresh_shareholder_snapshot(
    repository: Any,
    browser: Any,
    *,
    target_date: str,
    archive_bucket: Any | None = None,
) -> dict[str, Any]:
    datetime.fromisoformat(target_date)
    rows, browser_metadata = await fetch_top20(browser)
    share_count = await _latest_share_count(repository)
    total_issued = int(share_count["total_shares"]) if share_count and share_count.get("total_shares") else None
    validate_rows(rows, total_issued_shares=total_issued)
    result = await store_snapshot(
        repository,
        rows,
        snapshot_date=target_date,
        archive_bucket=archive_bucket,
        browser_metadata=browser_metadata,
    )
    return {
        **result,
        "source_url": EURONEXT_TOP20_URL,
        "captured_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }

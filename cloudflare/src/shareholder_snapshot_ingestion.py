from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any

try:
    from .r2_archive import archive_bytes
    from .shareholder_top20_browser import EURONEXT_TOP20_URL, EXPECTED_ROWS, fetch_top20
except ImportError:
    from r2_archive import archive_bytes
    from shareholder_top20_browser import EURONEXT_TOP20_URL, EXPECTED_ROWS, fetch_top20

SOURCE_KIND = "EURONEXT_OMS"


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value).replace("\u00a0", " ")).strip()


def validate_rows(
    rows: list[dict[str, Any]],
    *,
    total_issued_shares: int | None = None,
) -> list[dict[str, Any]]:
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
    return (
        json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


async def _latest_share_count(repository: Any) -> dict[str, Any] | None:
    return await repository.first(
        """
        SELECT total_shares, treasury_shares, outstanding_shares
        FROM otello_share_counts
        ORDER BY effective_from DESC, id DESC
        LIMIT 1
        """
    )


async def _snapshot_rows(repository: Any, snapshot_id: int) -> list[dict[str, Any]]:
    return await repository.all(
        """
        SELECT rank, shareholder_name, country, shares, ownership_pct, account_type
        FROM shareholder_snapshot_rows
        WHERE snapshot_id = ?
        ORDER BY rank ASC
        """,
        (snapshot_id,),
    )


def _rows_hash(rows: list[dict[str, Any]]) -> str | None:
    if len(rows) != EXPECTED_ROWS:
        return None
    return hashlib.sha256(canonical_rows(rows)).hexdigest()


async def _previous_snapshot(repository: Any, snapshot_date: str) -> dict[str, Any] | None:
    return await repository.first(
        """
        SELECT id, snapshot_date
        FROM shareholder_snapshots
        WHERE source_kind = ? AND snapshot_date < ?
        ORDER BY snapshot_date DESC, id DESC
        LIMIT 1
        """,
        (SOURCE_KIND, snapshot_date),
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
    total_issued = (
        int(share_count["total_shares"])
        if share_count and share_count.get("total_shares")
        else None
    )
    rows = validate_rows(rows, total_issued_shares=total_issued)
    canonical = canonical_rows(rows)
    content_hash = hashlib.sha256(canonical).hexdigest()

    # A retry for the same date must be idempotent. An unchanged list on a NEW date,
    # however, is still stored so the dashboard can truthfully compare today with yesterday.
    existing = await repository.first(
        "SELECT id FROM shareholder_snapshots WHERE snapshot_date=? AND source_kind=? LIMIT 1",
        (snapshot_date, SOURCE_KIND),
    )
    if existing is not None:
        existing_rows = await _snapshot_rows(repository, int(existing["id"]))
        if _rows_hash(existing_rows) == content_hash:
            return {
                "status": "unchanged_same_day",
                "snapshot_id": int(existing["id"]),
                "snapshot_date": snapshot_date,
                "rows": EXPECTED_ROWS,
                "content_sha256": content_hash,
                "stored": False,
                **browser_metadata,
            }

    previous_snapshot = await _previous_snapshot(repository, snapshot_date)
    previous_rows = (
        await _snapshot_rows(repository, int(previous_snapshot["id"]))
        if previous_snapshot is not None
        else []
    )
    previous_hash = _rows_hash(previous_rows)
    content_changed = None if previous_hash is None else previous_hash != content_hash
    previous_snapshot_date = (
        str(previous_snapshot["snapshot_date"]) if previous_snapshot is not None else None
    )

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
            "content_changed_from_previous": content_changed,
            "previous_snapshot_date": previous_snapshot_date,
            "permission_basis": "PROJECT_OWNER_CONFIRMED_PERMISSION_2026-08-19",
            "r2_key": archived.get("r2_key") if archived else None,
        },
    )

    if existing is not None:
        await repository.run(
            "DELETE FROM shareholder_snapshots WHERE id=?",
            (int(existing["id"]),),
        )

    notes = json.dumps(
        {
            "content_sha256": content_hash,
            "source_document_id": document_id,
            "r2_key": archived.get("r2_key") if archived else None,
            "content_changed_from_previous": content_changed,
            "previous_snapshot_date": previous_snapshot_date,
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
            int(share_count["treasury_shares"])
            if share_count and share_count.get("treasury_shares") is not None
            else None,
            int(share_count["outstanding_shares"])
            if share_count and share_count.get("outstanding_shares") is not None
            else None,
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
        row_sql = """
            INSERT INTO shareholder_snapshot_rows(
                snapshot_id, rank, shareholder_name, country, shares, ownership_pct, account_type
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        statements = [
            repository.database.prepare(row_sql).bind(
                snapshot_id,
                int(row["rank"]),
                str(row["shareholder_name"]),
                row.get("country"),
                int(row["shares"]),
                row.get("ownership_pct"),
                row.get("account_type"),
            )
            for row in rows
        ]
        # D1 batch is transactional: one malformed row rolls back all 20 row writes.
        await repository.database.batch(statements)
    except Exception:
        # Remove the header row too, so the dashboard never sees a partial snapshot.
        await repository.run("DELETE FROM shareholder_snapshots WHERE id=?", (snapshot_id,))
        raise

    stored_count = await repository.first(
        "SELECT COUNT(*) AS count FROM shareholder_snapshot_rows WHERE snapshot_id=?",
        (snapshot_id,),
    )
    if stored_count is None or int(stored_count["count"]) != EXPECTED_ROWS:
        await repository.run("DELETE FROM shareholder_snapshots WHERE id=?", (snapshot_id,))
        raise RuntimeError("Top 20-snapshot ble ikke lagret komplett")

    return {
        "status": "stored",
        "stored": True,
        "snapshot_id": snapshot_id,
        "snapshot_date": snapshot_date,
        "previous_snapshot_date": previous_snapshot_date,
        "content_changed": content_changed,
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
    total_issued = (
        int(share_count["total_shares"])
        if share_count and share_count.get("total_shares")
        else None
    )
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

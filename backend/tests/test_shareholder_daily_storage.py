from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
if str(CLOUDFLARE_SRC) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE_SRC))

from shareholder_snapshot_ingestion import store_snapshot  # noqa: E402


class _Statement:
    def __init__(self, sql: str):
        self.sql = sql

    def bind(self, *args):
        return self.sql, args


class _Database:
    def __init__(self, repository):
        self.repository = repository

    def prepare(self, sql: str):
        return _Statement(sql)

    async def batch(self, statements):
        for _sql, args in statements:
            snapshot_id, rank, name, country, shares, ownership, account_type = args
            self.repository.rows.setdefault(int(snapshot_id), []).append(
                {
                    "rank": int(rank),
                    "shareholder_name": str(name),
                    "country": country,
                    "shares": int(shares),
                    "ownership_pct": ownership,
                    "account_type": account_type,
                }
            )
        return []


class _Repository:
    def __init__(self):
        self.snapshots: list[dict] = []
        self.rows: dict[int, list[dict]] = {}
        self.next_id = 1
        self.database = _Database(self)

    async def create_source_document(self, **_kwargs):
        return 101

    async def first(self, sql: str, params=()):
        compact = " ".join(sql.split())
        if "FROM otello_share_counts" in compact:
            return {
                "total_shares": 73_790_829,
                "treasury_shares": 3_000_000,
                "outstanding_shares": 70_790_829,
            }
        if "source_kind = ? AND snapshot_date < ?" in compact:
            source_kind, target_date = params
            candidates = [
                item for item in self.snapshots
                if item["source_kind"] == source_kind and item["snapshot_date"] < target_date
            ]
            return max(candidates, key=lambda item: (item["snapshot_date"], item["id"])) if candidates else None
        if "WHERE snapshot_date=? AND source_kind=?" in compact:
            target_date, source_kind = params
            return next(
                (
                    {"id": item["id"]}
                    for item in self.snapshots
                    if item["snapshot_date"] == target_date and item["source_kind"] == source_kind
                ),
                None,
            )
        if "COUNT(*) AS count FROM shareholder_snapshot_rows" in compact:
            snapshot_id = int(params[0])
            return {"count": len(self.rows.get(snapshot_id, []))}
        raise AssertionError(f"Unhandled first SQL: {compact}")

    async def all(self, sql: str, params=()):
        compact = " ".join(sql.split())
        if "FROM shareholder_snapshot_rows" in compact:
            return [dict(row) for row in sorted(self.rows.get(int(params[0]), []), key=lambda row: row["rank"])]
        raise AssertionError(f"Unhandled all SQL: {compact}")

    async def run(self, sql: str, params=()):
        compact = " ".join(sql.split())
        if compact.startswith("DELETE FROM shareholder_snapshots"):
            snapshot_id = int(params[0])
            self.snapshots = [item for item in self.snapshots if item["id"] != snapshot_id]
            self.rows.pop(snapshot_id, None)
            return None
        if compact.startswith("INSERT INTO shareholder_snapshots"):
            snapshot_date, source_url, source_kind, total, treasury, outstanding, notes = params
            snapshot_id = self.next_id
            self.next_id += 1
            self.snapshots.append(
                {
                    "id": snapshot_id,
                    "snapshot_date": snapshot_date,
                    "source_url": source_url,
                    "source_kind": source_kind,
                    "total_issued_shares": total,
                    "treasury_shares": treasury,
                    "outstanding_shares": outstanding,
                    "notes": notes,
                }
            )
            return None
        raise AssertionError(f"Unhandled run SQL: {compact}")


def _rows() -> list[dict]:
    return [
        {
            "rank": rank,
            "shareholder_name": f"Investor {rank} AS",
            "country": "NOR",
            "shares": 2_000_000 - rank * 10_000,
            "ownership_pct": "1.00",
            "account_type": "Comp.",
        }
        for rank in range(1, 21)
    ]


@pytest.mark.asyncio
async def test_identical_top20_is_stored_on_a_new_day_but_retry_is_idempotent() -> None:
    repository = _Repository()
    browser_metadata = {"method": "scrape", "browser_calls": 1, "browser_ms": 123}

    first = await store_snapshot(
        repository,
        _rows(),
        snapshot_date="2026-08-19",
        archive_bucket=None,
        browser_metadata=browser_metadata,
    )
    second = await store_snapshot(
        repository,
        _rows(),
        snapshot_date="2026-08-20",
        archive_bucket=None,
        browser_metadata=browser_metadata,
    )
    retry = await store_snapshot(
        repository,
        _rows(),
        snapshot_date="2026-08-20",
        archive_bucket=None,
        browser_metadata=browser_metadata,
    )

    assert first["status"] == "stored"
    assert first["content_changed"] is None
    assert second["status"] == "stored"
    assert second["content_changed"] is False
    assert second["previous_snapshot_date"] == "2026-08-19"
    assert retry["status"] == "unchanged_same_day"
    assert retry["stored"] is False
    assert len(repository.snapshots) == 2
    assert [item["snapshot_date"] for item in repository.snapshots] == ["2026-08-19", "2026-08-20"]
    assert all(len(repository.rows[item["id"]]) == 20 for item in repository.snapshots)

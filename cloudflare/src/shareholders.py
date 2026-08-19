from __future__ import annotations

from typing import Any

try:
    from .performance_repository import PerformanceD1Repository
except ImportError:
    from performance_repository import PerformanceD1Repository


OTELLO_SHAREHOLDERS_PAGE = "https://www.otellocorp.com/ir/shares/major-shareholders"
EURONEXT_TOP20_URL = "https://ir.oms.no/component/shareholders?lang=en&token=opera"
OTELLO_IDENTIFICATION_XLSX = (
    "https://otello.cdn.prismic.io/otello/"
    "aemxxcBOoF08xO8y_OtelloCorporationASAShareholderListMar26.xlsx"
)


async def _latest_share_count(repository: PerformanceD1Repository) -> dict[str, Any] | None:
    return await repository.first(
        """
        SELECT osc.effective_from, osc.total_shares, osc.treasury_shares,
               osc.outstanding_shares, sd.url AS source_url, s.code AS source_code
        FROM otello_share_counts osc
        JOIN source_documents sd ON sd.id = osc.source_document_id
        JOIN sources s ON s.id = sd.source_id
        ORDER BY osc.effective_from DESC, osc.id DESC
        LIMIT 1
        """
    )


async def _snapshots(repository: PerformanceD1Repository, limit: int = 12) -> list[dict[str, Any]]:
    rows = await repository.all(
        """
        SELECT ss.id, ss.snapshot_date, ss.source_url, ss.source_kind,
               ss.total_issued_shares, ss.treasury_shares, ss.outstanding_shares,
               ss.captured_at, COUNT(sr.id) AS row_count,
               COALESCE(SUM(sr.shares), 0) AS top20_shares
        FROM shareholder_snapshots ss
        LEFT JOIN shareholder_snapshot_rows sr ON sr.snapshot_id = ss.id
        GROUP BY ss.id
        ORDER BY ss.snapshot_date DESC, ss.id DESC
        LIMIT ?
        """,
        (limit,),
    )
    result = []
    for row in rows:
        item = dict(row)
        total = item.get("total_issued_shares")
        top20 = int(item.get("top20_shares") or 0)
        item["top20_shares"] = top20
        item["top20_pct"] = None if not total else top20 / int(total) * 100
        result.append(item)
    return result


async def _rows(repository: PerformanceD1Repository, snapshot_id: int) -> list[dict[str, Any]]:
    return await repository.all(
        """
        SELECT rank, shareholder_name, country, shares, ownership_pct, account_type
        FROM shareholder_snapshot_rows
        WHERE snapshot_id = ?
        ORDER BY rank ASC
        """,
        (snapshot_id,),
    )


def _movement(current: list[dict[str, Any]], previous: list[dict[str, Any]]) -> dict[str, Any]:
    current_by_name = {str(item["shareholder_name"]): item for item in current}
    previous_by_name = {str(item["shareholder_name"]): item for item in previous}
    changes = []
    for name in sorted(set(current_by_name) | set(previous_by_name)):
        cur = current_by_name.get(name)
        prev = previous_by_name.get(name)
        cur_shares = int(cur["shares"]) if cur else 0
        prev_shares = int(prev["shares"]) if prev else 0
        changes.append(
            {
                "shareholder_name": name,
                "current_shares": cur_shares,
                "previous_shares": prev_shares,
                "change_shares": cur_shares - prev_shares,
                "current_rank": cur.get("rank") if cur else None,
                "previous_rank": prev.get("rank") if prev else None,
                "new_in_top20": prev is None and cur is not None,
                "exited_top20": cur is None and prev is not None,
            }
        )
    active = [item for item in changes if item["change_shares"] != 0]
    return {
        "changes": active,
        "biggest_buyers": [item for item in sorted(active, key=lambda x: x["change_shares"], reverse=True) if item["change_shares"] > 0][:5],
        "biggest_sellers": [item for item in sorted(active, key=lambda x: x["change_shares"]) if item["change_shares"] < 0][:5],
        "new_entries": [item for item in changes if item["new_in_top20"]],
        "exits": [item for item in changes if item["exited_top20"]],
    }


async def shareholders_dashboard(repository: PerformanceD1Repository) -> dict[str, Any]:
    share_count = await _latest_share_count(repository)
    snapshots = await _snapshots(repository)
    latest_rows: list[dict[str, Any]] = []
    movement: dict[str, Any] | None = None
    if snapshots:
        latest_rows = await _rows(repository, int(snapshots[0]["id"]))
    if len(snapshots) >= 2:
        previous_rows = await _rows(repository, int(snapshots[1]["id"]))
        movement = _movement(latest_rows, previous_rows)

    return {
        "ready": True,
        "official_live": {
            "title": "Top 20 largest shareholders",
            "updated_frequency": "WEEKLY",
            "source": "Otello IR / Euronext OMS",
            "source_page_url": OTELLO_SHAREHOLDERS_PAGE,
            "embed_url": EURONEXT_TOP20_URL,
        },
        "shareholder_identification": {
            "as_of_date": "2026-03-04",
            "source": "Otello IR",
            "url": OTELLO_IDENTIFICATION_XLSX,
            "format": "XLSX",
        },
        "share_count": share_count,
        "history": {
            "snapshot_count": len(snapshots),
            "comparison_ready": len(snapshots) >= 2,
            "snapshots": snapshots,
            "latest_rows": latest_rows,
            "movement": movement,
            "note": (
                "Den offisielle Euronext-listen vises live. Uke-for-uke-endringer beregnes "
                "fra snapshots som lagres i trackerens egen database."
            ),
        },
    }

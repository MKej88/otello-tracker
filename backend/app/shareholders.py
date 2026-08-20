from __future__ import annotations

from datetime import date
from typing import Any

from app.db.connection import get_connection


OTELLO_SHAREHOLDERS_PAGE = "https://www.otellocorp.com/ir/shares/major-shareholders"
EURONEXT_TOP20_URL = "https://ir.oms.no/component/shareholders?lang=en&token=opera"
OTELLO_IDENTIFICATION_XLSX = (
    "https://otello.cdn.prismic.io/otello/"
    "aemxxcBOoF08xO8y_OtelloCorporationASAShareholderListMar26.xlsx"
)
SOURCE_KIND = "EURONEXT_OMS"


def _latest_share_count(connection) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT osc.effective_from, osc.total_shares, osc.treasury_shares,
               osc.outstanding_shares, sd.url AS source_url, s.code AS source_code
        FROM otello_share_counts osc
        JOIN source_documents sd ON sd.id = osc.source_document_id
        JOIN sources s ON s.id = sd.source_id
        ORDER BY osc.effective_from DESC, osc.id DESC
        LIMIT 1
        """
    ).fetchone()
    return dict(row) if row is not None else None


def _snapshots(connection, limit: int = 31) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT ss.id, ss.snapshot_date, ss.source_url, ss.source_kind,
               ss.total_issued_shares, ss.treasury_shares, ss.outstanding_shares,
               ss.captured_at, COUNT(sr.id) AS row_count,
               COALESCE(SUM(sr.shares), 0) AS top20_shares
        FROM shareholder_snapshots ss
        LEFT JOIN shareholder_snapshot_rows sr ON sr.snapshot_id = ss.id
        WHERE ss.source_kind = ?
        GROUP BY ss.id
        ORDER BY ss.snapshot_date DESC, ss.id DESC
        LIMIT ?
        """,
        (SOURCE_KIND, limit),
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        total = item.get("total_issued_shares")
        top20 = int(item.get("top20_shares") or 0)
        item["top20_shares"] = top20
        item["top20_pct"] = None if not total else top20 / int(total) * 100
        result.append(item)
    return result


def _rows(connection, snapshot_id: int) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in connection.execute(
            """
            SELECT rank, shareholder_name, country, shares, ownership_pct, account_type
            FROM shareholder_snapshot_rows
            WHERE snapshot_id = ?
            ORDER BY rank ASC
            """,
            (snapshot_id,),
        ).fetchall()
    ]


def _movement(current: list[dict[str, Any]], previous: list[dict[str, Any]]) -> dict[str, Any]:
    current_by_name = {str(item["shareholder_name"]): item for item in current}
    previous_by_name = {str(item["shareholder_name"]): item for item in previous}

    names = sorted(set(current_by_name) | set(previous_by_name))
    changes = []
    for name in names:
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

    active_changes = [item for item in changes if item["change_shares"] != 0]
    buyers = sorted(active_changes, key=lambda item: item["change_shares"], reverse=True)
    sellers = sorted(active_changes, key=lambda item: item["change_shares"])
    return {
        "changes": active_changes,
        "biggest_buyers": [item for item in buyers if item["change_shares"] > 0][:5],
        "biggest_sellers": [item for item in sellers if item["change_shares"] < 0][:5],
        "new_entries": [item for item in changes if item["new_in_top20"]],
        "exits": [item for item in changes if item["exited_top20"]],
    }


def _daily_summary(
    snapshots: list[dict[str, Any]],
    movement: dict[str, Any] | None,
) -> dict[str, Any]:
    if not snapshots:
        return {
            "status": "NO_SNAPSHOT",
            "message": "Venter på første daglige Top 20-måling.",
            "latest_date": None,
            "previous_date": None,
            "is_previous_day": False,
            "change_count": 0,
        }

    latest_date = str(snapshots[0]["snapshot_date"])
    if len(snapshots) < 2:
        return {
            "status": "FIRST_SNAPSHOT",
            "message": "Første daglige måling er lagret. Sammenligning kommer etter neste måling.",
            "latest_date": latest_date,
            "previous_date": None,
            "is_previous_day": False,
            "change_count": 0,
        }

    previous_date = str(snapshots[1]["snapshot_date"])
    day_gap = (date.fromisoformat(latest_date) - date.fromisoformat(previous_date)).days
    is_previous_day = day_gap == 1
    changes = (movement or {}).get("changes") or []
    change_count = len(changes)
    if change_count == 0:
        message = (
            "Ingen endringer siden i går."
            if is_previous_day
            else f"Ingen endringer siden forrige måling ({previous_date})."
        )
        status = "NO_CHANGES"
    else:
        noun = "endring" if change_count == 1 else "endringer"
        message = (
            f"{change_count} {noun} siden i går."
            if is_previous_day
            else f"{change_count} {noun} siden forrige måling ({previous_date})."
        )
        status = "CHANGES"

    return {
        "status": status,
        "message": message,
        "latest_date": latest_date,
        "previous_date": previous_date,
        "is_previous_day": is_previous_day,
        "change_count": change_count,
    }


def shareholders_dashboard(database_path: str | None = None) -> dict[str, Any]:
    with get_connection(database_path) as connection:
        share_count = _latest_share_count(connection)
        snapshots = _snapshots(connection)
        latest_rows: list[dict[str, Any]] = []
        movement: dict[str, Any] | None = None
        if snapshots:
            latest_rows = _rows(connection, int(snapshots[0]["id"]))
        if len(snapshots) >= 2:
            previous_rows = _rows(connection, int(snapshots[1]["id"]))
            movement = _movement(latest_rows, previous_rows)
        daily_summary = _daily_summary(snapshots, movement)

    return {
        "ready": True,
        "official_live": {
            "title": "Top 20 largest shareholders",
            "updated_frequency": "DAILY",
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
            "daily_summary": daily_summary,
            "note": (
                "Top 20 hentes fra Euronext OMS hver dag og vises direkte i trackeren. "
                "Endringer beregnes mot forrige lagrede dagsmåling."
            ),
        },
    }

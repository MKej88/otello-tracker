from __future__ import annotations

from pathlib import Path

import app.estimated_nav_history as history_module
from app.db.connection import get_connection
from app.db.migration_runner import init_database


def test_materializer_replaces_point_older_than_full_nav(tmp_path, monkeypatch) -> None:
    database = str(tmp_path / "stale-history.db")
    init_database(database)

    with get_connection(database) as connection:
        connection.execute(
            """INSERT INTO nav_snapshots(
                   as_of_at, nav_total_nok, nav_per_share_nok, bemobi_value_nok,
                   cash_estimate_nok, other_net_assets_nok, shares_outstanding,
                   calculation_version, inputs_hash, status, nav_scope,
                   components_json, created_at, updated_at
               ) VALUES (
                   '2026-09-04T23:59:59Z', '110000000', '11', '70000000',
                   '30000000', '10000000', 10000000, ?, 'corrected-inputs',
                   'ESTIMATED', 'FULL', '{}', '2026-09-04T20:00:00Z',
                   '2026-09-05T20:00:00Z'
               )""",
            (history_module.FULL_CALCULATION_VERSION,),
        )
        connection.execute(
            """INSERT INTO estimated_nav_history_points(
                   date, calculation_version, nav_total_mnok, nav_per_share_nok,
                   shares_outstanding, composition_json, quality, calculated_at
               ) VALUES (
                   '2026-09-04', ?, 100, 10, 10000000, '[]', 'VALID',
                   '2026-09-04T21:00:00Z'
               )""",
            (history_module.ESTIMATED_NAV_CALCULATION_VERSION,),
        )
        connection.commit()

    monkeypatch.setattr(
        history_module,
        "_estimated_point",
        lambda *_args: {
            "ready": True,
            "nav_total_mnok": 110,
            "nav_per_share": 11,
            "otec_price": 8,
            "discount_pct": 27.27,
            "shares_outstanding": 10000000,
            "accounting_nav_per_share": 10,
            "composition": [],
            "reconciliation_residual_mnok": 0,
        },
    )

    result = history_module.materialize_estimated_nav_history(database)

    assert result["written"] == 1
    with get_connection(database) as connection:
        point = connection.execute("""SELECT nav_per_share_nok
               FROM estimated_nav_history_points
               WHERE date='2026-09-04'""").fetchone()
    assert point is not None
    assert point["nav_per_share_nok"] == 11


def test_production_materializer_can_revisit_stale_date_before_cursor() -> None:
    root = Path(__file__).resolve().parents[2]
    source = (
        root / "cloudflare" / "src" / "estimated_nav_history_materialization.py"
    ).read_text(encoding="utf-8")

    assert "p.calculated_at < COALESCE(n.updated_at, n.created_at)" in source
    assert "p.date IS NULL AND (? IS NULL OR substr(n.as_of_at, 1, 10) > ?)" in source

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
TOOLS = Path(__file__).resolve().parent
for path in (BACKEND, TOOLS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from build_d1_bootstrap_fixture import build_fixture  # noqa: E402
from app.bemobi.consensus import bemobi_consensus as reference_bemobi_consensus  # noqa: E402
from app.buybacks import buyback_forecast as reference_buyback_forecast  # noqa: E402
from app.buybacks.activity import seed_otec_activity_history  # noqa: E402
from app.dashboard import dashboard_history as reference_dashboard_history  # noqa: E402
from app.dashboard import dashboard_summary as reference_dashboard_summary  # noqa: E402
from app.dashboard_freshness import enrich_dashboard_summary  # noqa: E402
from app.db.connection import get_connection  # noqa: E402
from app.economic_nav_investor import economic_nav_summary as reference_economic_nav_summary  # noqa: E402
from app.nav.daily_nav import CALCULATION_VERSION as CORE_VERSION  # noqa: E402
from app.nav.full_nav import FULL_CALCULATION_VERSION as FULL_VERSION  # noqa: E402
from app.shareholders import shareholders_dashboard as reference_shareholders_dashboard  # noqa: E402


def _components(*, day: str, otec: str, bmob3: str, brl: str, cash: str, status: str) -> str:
    return json.dumps(
        {
            "bmob3": {
                "price_brl": bmob3,
                "brl_nok": brl,
                "price_source": "B3",
                "price_quality": "DIRECT",
                "price_date": day,
                "price_observed_at": f"{day}T20:00:00Z",
                "price_type": "CLOSE",
                "brl_nok_date": day,
            },
            "otec": {
                "price_nok": otec,
                "price_source": "EURONEXT",
                "price_quality": "DIRECT",
                "price_date": day,
                "price_observed_at": f"{day}T14:30:00Z",
                "price_type": "LAST",
                "share_count_quality": "REPORTED",
            },
            "cash": {
                "cash_nok": cash,
                "quality": "FORECAST_PARTIAL" if status == "DEGRADED" else "ANCHORED_ESTIMATE",
                "calibration_quality": "ANCHORED",
            },
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def _full_components(*, day: str) -> str:
    return json.dumps(
        {
            "other_net_assets": {
                "option_liability": {
                    "amount_nok": "2600000",
                    "fair_value_per_option_nok": "5.902439024390244",
                    "strike_nok": "12.5637",
                    "inputs": {
                        "option_count": 4100000,
                        "strike_nok": "12.5637",
                        "gross_fair_value_nok": "24200000",
                        "fixture_date": day,
                    },
                    "quality": "FORECAST_MARK_TO_MARKET",
                }
            }
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def _insert_nav_pair(
    connection,
    *,
    day: str,
    nav: str,
    otec: str,
    discount: str,
    cash: str,
    bmob3: str,
    brl: str,
    status: str,
) -> None:
    components = _components(
        day=day,
        otec=otec,
        bmob3=bmob3,
        brl=brl,
        cash=cash,
        status=status,
    )
    full_components = _full_components(day=day)
    as_of_at = f"{day}T23:59:59Z"
    shares = 70_000_000
    connection.execute(
        """
        INSERT INTO nav_snapshots(
            as_of_at, nav_total_nok, nav_per_share_nok, otec_price_nok,
            discount_pct, bemobi_value_nok, cash_estimate_nok,
            other_net_assets_nok, shares_outstanding, calculation_version,
            inputs_hash, status, nav_scope, components_json, quality_notes
        ) VALUES (?, '1500000000', ?, ?, ?, '1350000000', ?, '0', ?, ?, ?, ?, 'CORE', ?, 'worker runtime parity')
        """,
        (
            as_of_at,
            nav,
            otec,
            discount,
            cash,
            shares,
            CORE_VERSION,
            f"worker-core-{day}",
            status,
            components,
        ),
    )
    full_nav = str(float(nav) + 0.15)
    connection.execute(
        """
        INSERT INTO nav_snapshots(
            as_of_at, nav_total_nok, nav_per_share_nok, otec_price_nok,
            discount_pct, bemobi_value_nok, cash_estimate_nok,
            other_net_assets_nok, shares_outstanding, calculation_version,
            inputs_hash, status, nav_scope, components_json, quality_notes
        ) VALUES (?, '1510500000', ?, ?, ?, '1350000000', ?, '10500000', ?, ?, ?, ?, 'FULL', ?, 'worker runtime parity')
        """,
        (
            as_of_at,
            full_nav,
            otec,
            discount,
            cash,
            shares,
            FULL_VERSION,
            f"worker-full-{day}",
            status,
            full_components,
        ),
    )


def build_worker_runtime_fixture(database_path: str, expected_dir: Path) -> dict:
    result = build_fixture(database_path)

    with get_connection(database_path) as connection:
        connection.execute("DELETE FROM market_activity")
        connection.execute("DELETE FROM nav_snapshots")
        source_id = int(connection.execute("SELECT id FROM sources WHERE code='ECB'").fetchone()["id"])
        connection.executemany(
            """
            INSERT INTO fx_rates(base_currency, quote_currency, observed_at, rate, source_id)
            VALUES (?, 'NOK', ?, ?, ?)
            ON CONFLICT(base_currency, quote_currency, observed_at, source_id)
            DO UPDATE SET rate=excluded.rate
            """,
            [
                ("USD", "2025-12-31T00:00:00Z", "10.08", source_id),
                ("BRL", "2025-12-31T00:00:00Z", "1.74", source_id),
            ],
        )
        connection.commit()
    seed_otec_activity_history(database_path)

    with get_connection(database_path) as connection:
        _insert_nav_pair(
            connection,
            day="2026-08-13",
            nav="23.00",
            otec="17.86",
            discount="22.34782608695652",
            cash="160000000",
            bmob3="22.88",
            brl="1.90",
            status="ESTIMATED",
        )
        _insert_nav_pair(
            connection,
            day="2026-08-14",
            nav="23.50",
            otec="17.20",
            discount="26.80851063829787",
            cash="158000000",
            bmob3="22.81",
            brl="1.91",
            status="ESTIMATED",
        )
        connection.commit()

    expected_dir.mkdir(parents=True, exist_ok=True)
    expected = {
        "summary": enrich_dashboard_summary(reference_dashboard_summary(database_path), database_path),
        "economic": reference_economic_nav_summary(database_path),
        "history": reference_dashboard_history(database_path, days=365, max_points=300),
        "forecast": reference_buyback_forecast(database_path, as_of_date="2026-08-17"),
        "consensus": reference_bemobi_consensus(database_path),
        "shareholders": reference_shareholders_dashboard(database_path),
    }
    for name, payload in expected.items():
        (expected_dir / f"{name}.json").write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str),
            encoding="utf-8",
        )

    return {
        **result,
        "expected_dir": str(expected_dir),
        "forecast_ready": bool(expected["forecast"].get("ready")),
        "summary_ready": bool(expected["summary"].get("ready")),
        "economic_ready": bool(expected["economic"].get("ready")),
        "consensus_ready": bool(expected["consensus"].get("ready")),
        "shareholders_ready": bool(expected["shareholders"].get("ready")),
        "history_points": len(expected["history"].get("points", [])),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build populated Worker/D1 HTTP parity fixture")
    parser.add_argument("--database", required=True)
    parser.add_argument("--expected-dir", required=True)
    args = parser.parse_args()
    result = build_worker_runtime_fixture(args.database, Path(args.expected_dir))
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()

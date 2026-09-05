from __future__ import annotations

from pathlib import Path

from app.buybacks.activity import seed_otec_activity_history
from app.buybacks.forecast import buyback_forecast
from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.db.repository import create_source_document

ROOT = Path(__file__).resolve().parents[2]


def _seed_program(database: str) -> None:
    weeks = [
        ("2026-06-08", "2026-06-12", 79_600, 79_600),
        ("2026-06-15", "2026-06-19", 72_009, 151_609),
        ("2026-06-22", "2026-06-26", 52_419, 204_028),
        ("2026-06-29", "2026-07-03", 63_554, 267_582),
        ("2026-07-06", "2026-07-10", 65_300, 332_882),
        ("2026-07-13", "2026-07-17", 52_599, 385_481),
        ("2026-07-20", "2026-07-24", 50_500, 435_981),
        ("2026-07-27", "2026-07-31", 46_400, 482_381),
        ("2026-08-03", "2026-08-07", 58_500, 540_881),
        ("2026-08-10", "2026-08-14", 59_512, 600_393),
    ]
    with get_connection(database) as connection:
        document_id = create_source_document(
            connection,
            source_code="NEWSWEB",
            external_id="weekend-continuity-program",
            document_type="REGULATORY_NEWS",
            title="Weekend continuity program",
            url="https://newsweb.oslobors.no/message/weekend-continuity",
        )
        cursor = connection.execute(
            """
            INSERT INTO buyback_programs(
                external_program_id, announced_at, start_date, max_shares,
                max_price_nok, status, source_document_id, notes
            ) VALUES ('otec-buyback-weekend-test', '2026-06-08T00:00:00Z',
                      '2026-06-08', 2192046, '20', 'ACTIVE', ?, 'test')
            """,
            (document_id,),
        )
        program_id = int(cursor.lastrowid)
        for start, end, shares, cumulative in weeks:
            connection.execute(
                """
                INSERT INTO buybacks(
                    program_id, period_start, trade_date, shares, avg_price_nok, amount_nok,
                    cumulative_program_shares, treasury_shares_after, source_document_id
                ) VALUES (?, ?, ?, ?, '17', ?, ?, ?, ?)
                """,
                (
                    program_id,
                    start,
                    end,
                    shares,
                    str(shares * 17),
                    cumulative,
                    5_000_000 + cumulative,
                    document_id,
                ),
            )
        connection.commit()


def test_saturday_keeps_last_forecast_and_walk_forward_history(tmp_path) -> None:
    database = str(tmp_path / "weekend.db")
    init_database(database)
    seed_otec_activity_history(database)
    _seed_program(database)

    # Latest reported week ends 14.08, so the ex-ante forecast covers 17–21.08.
    # Saturday 22.08 must retain that last forecast while awaiting the next report.
    result = buyback_forecast(database, as_of_date="2026-08-22")

    assert result["ready"] is True
    assert result["status"] in {"OK", "PRICE_CAP_BLOCKED"}
    assert result["awaiting_program_update"] is True
    assert result["forecast_week"]["from"] == "2026-08-17"
    assert result["forecast_week"]["to"] == "2026-08-21"
    assert result["estimate"]["base_case_shares"] is not None
    assert result["active_program_backtest"]["weeks"] > 0
    assert result["recent_program_weeks"]


def test_worker_does_not_drop_forecast_after_friday() -> None:
    worker = (ROOT / "cloudflare" / "src" / "buyback_service.py").read_text(
        encoding="utf-8"
    )
    reference = (ROOT / "backend" / "app" / "buybacks" / "forecast.py").read_text(
        encoding="utf-8"
    )

    for source in (worker, reference):
        assert "PROGRAM_STATUS_STALE" not in source
        assert "awaiting_program_update = as_of > period_end" in source
        assert '"awaiting_program_update": awaiting_program_update' in source

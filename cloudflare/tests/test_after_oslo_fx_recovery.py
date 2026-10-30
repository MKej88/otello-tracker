from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import UTC, date, datetime, timedelta

from src.after_oslo_fx import (
    REFERENCE_PREFIX,
    fx_close_movement,
    recover_fx_close_reference,
)
from src.bemobi_after_oslo import iso
from src.oslo_calendar import closing_auction
from src.runtime_status import _oslo_close_fx_quality


CLOSE = closing_auction(date(2026, 10, 30)).astimezone(UTC)
OBSERVED = iso(CLOSE - timedelta(minutes=1))
NOW = CLOSE + timedelta(minutes=80)
REFERENCE_KEY = REFERENCE_PREFIX + "2026-10-30"


class Repository:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript("""
            CREATE TABLE sources(id INTEGER PRIMARY KEY, code TEXT);
            INSERT INTO sources VALUES (1,'NORGES_BANK'),(2,'EXCHANGERATE_DEV');
            CREATE TABLE fx_rates(
                id INTEGER PRIMARY KEY,
                base_currency TEXT,
                quote_currency TEXT,
                observed_at TEXT,
                rate TEXT,
                source_id INTEGER
            );
            CREATE TABLE runtime_state(
                key TEXT PRIMARY KEY, value TEXT, updated_at TEXT
            );
        """)

    def quote(self, at: str, rate: str, source: int = 2):
        self.conn.execute(
            "INSERT INTO fx_rates(base_currency,quote_currency,observed_at,rate,source_id) VALUES ('BRL','NOK',?,?,?)",
            (at, rate, source),
        )

    def official(self, rate="1.72"):
        self.quote(iso(CLOSE - timedelta(days=1)), rate, source=1)

    def capture_attempt(self, reason: str, error_type: str | None = None,
                        observed_at: str | None = None):
        self.conn.execute(
            "INSERT INTO runtime_state(key,value,updated_at) VALUES (?,?,?)",
            (
                "brlnok_oslo_capture_last_result",
                json.dumps({"status": "skipped", "reason": reason,
                            "error_type": error_type, "observed_at": observed_at}),
                iso(CLOSE + timedelta(minutes=17)),
            ),
        )

    async def first(self, sql, args=()):
        row = self.conn.execute(sql, args).fetchone()
        return dict(row) if row else None

    async def run(self, sql, args=()):
        self.conn.execute(sql, args)

    def reference(self):
        row = self.conn.execute(
            "SELECT value FROM runtime_state WHERE key=?", (REFERENCE_KEY,)
        ).fetchone()
        return json.loads(row["value"]) if row else None


def test_recover_from_exact_stored_intraday_quote_and_use_later_live_fx():
    repo = Repository()
    repo.official()
    repo.quote(OBSERVED, "1.7100")
    repo.quote(iso(CLOSE + timedelta(minutes=35)), "1.7400")
    result = asyncio.run(recover_fx_close_reference(repo, now=NOW))
    assert result["status"] == "ok"
    assert result["reason"] == "recovered_from_stored_quote"
    assert repo.reference()["recovered"] is True
    assert repo.reference()["observed_at"] == OBSERVED
    move = asyncio.run(fx_close_movement(repo, CLOSE, NOW))
    assert move["ready"] is True
    assert move["reference_rate"] == 1.71
    assert move["latest_rate"] == 1.74
    again = asyncio.run(recover_fx_close_reference(repo, now=NOW))
    assert again == {"status": "skipped", "reason": "already_captured"}


def test_later_spot_or_daily_norges_bank_fix_never_fabricates_close():
    repo = Repository()
    repo.official()
    repo.quote(iso(CLOSE - timedelta(minutes=4)), "1.7100")
    repo.quote(iso(CLOSE + timedelta(minutes=1)), "1.7350")
    result = asyncio.run(recover_fx_close_reference(repo, now=NOW))
    assert result == {"status": "missing", "reason": "no_valid_stored_reference"}
    assert repo.reference() is None
    assert not asyncio.run(fx_close_movement(repo, CLOSE, NOW))["ready"]


def test_reject_deviation_from_official_and_absent_official():
    repo = Repository()
    repo.quote(OBSERVED, "1.7100")
    result = asyncio.run(recover_fx_close_reference(repo, now=NOW))
    assert result["reason"] == "missing_sanity_reference"
    repo.official("2.50")
    result = asyncio.run(recover_fx_close_reference(repo, now=NOW))
    assert result["reason"] == "deviation_from_official_rate"
    assert repo.reference() is None


def test_does_not_repair_before_original_capture_window_ends():
    repo = Repository()
    repo.official()
    repo.quote(OBSERVED, "1.7100")
    outcome = asyncio.run(
        recover_fx_close_reference(repo, now=CLOSE + timedelta(minutes=15))
    )
    assert outcome["reason"] == "awaiting_reference_window"
    assert repo.reference() is None


def test_quality_reports_exact_capture_failure_without_raw_provider_text():
    repo = Repository()
    repo.capture_attempt(
        "observation_not_near_oslo_close",
        observed_at=iso(CLOSE - timedelta(minutes=5)),
    )
    result = asyncio.run(_oslo_close_fx_quality(repo, now=NOW))
    assert result["status"] == "DEGRADED"
    assert result["reason"] == "missing_oslo_close_fx_reference"
    assert result["capture_reason"] == "observation_not_near_oslo_close"
    assert result["capture_observed_at"] == iso(CLOSE - timedelta(minutes=5))
    assert result["capture_checked_at"] is not None


def test_quality_whitelists_error_codes_and_stale_capture_records():
    repo = Repository()
    repo.capture_attempt("private https://example.invalid?key=secret", "SecretsException")
    result = asyncio.run(_oslo_close_fx_quality(repo, now=NOW))
    assert result["capture_reason"] is None
    assert result["capture_error_type"] is None
    assert "secret" not in str(result)
    repo.conn.execute(
        "UPDATE runtime_state SET updated_at=? WHERE key='brlnok_oslo_capture_last_result'",
        (iso(CLOSE - timedelta(days=1)),),
    )
    result = asyncio.run(_oslo_close_fx_quality(repo, now=NOW))
    assert result["capture_reason"] is None
    assert result["capture_checked_at"] is None


def test_quality_waits_for_later_quote_after_valid_reference():
    repo = Repository()
    repo.official()
    repo.quote(OBSERVED, "1.7100")
    asyncio.run(recover_fx_close_reference(repo, now=NOW))
    before = asyncio.run(
        _oslo_close_fx_quality(repo, now=CLOSE + timedelta(minutes=25))
    )
    assert before["status"] == "WAITING"
    assert before["reason"] == "missing_fx_after_oslo_close"
    repo.quote(iso(CLOSE + timedelta(minutes=35)), "1.7500")
    after = asyncio.run(_oslo_close_fx_quality(repo, now=NOW))
    assert after["status"] == "OK"
    assert after["reason"] is None

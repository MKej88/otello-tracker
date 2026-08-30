from datetime import date

from app.jobs.refresh_helpers import (
    eod_is_authoritative,
    previous_oslo_trading_day,
    safe_step,
)


def test_safe_step_returns_value_without_recording_an_error() -> None:
    errors: list[dict[str, str]] = []

    assert safe_step("provider", lambda: {"status": "ok"}, errors) == {"status": "ok"}
    assert errors == []


def test_safe_step_records_error_and_allows_refresh_to_continue() -> None:
    errors: list[dict[str, str]] = []

    def fail() -> None:
        raise RuntimeError("midlertidig feil")

    assert safe_step("provider", fail, errors) is None
    assert errors == [{"step": "provider", "error": "midlertidig feil"}]


def test_previous_oslo_trading_day_skips_weekend() -> None:
    assert previous_oslo_trading_day(date(2026, 8, 31)) == date(2026, 8, 28)


def test_only_completed_eod_results_are_authoritative() -> None:
    assert eod_is_authoritative({"status": "ok"}) is True
    assert eod_is_authoritative({"status": "no_trade"}) is True
    assert (
        eod_is_authoritative({"status": "skipped", "reason": "eod_already_finalized"})
        is True
    )
    assert eod_is_authoritative({"status": "skipped", "reason": "market_open"}) is False
    assert eod_is_authoritative(None) is False

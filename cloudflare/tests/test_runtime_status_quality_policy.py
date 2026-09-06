from __future__ import annotations

from src.runtime_status import _dashboard_quality_reasons, _expected_between_reports


def test_normal_between_report_estimates_are_not_active_warnings() -> None:
    details = {
        "data_status": "DEGRADED",
        "cash_quality": "FORECAST_PARTIAL",
        "cash_calibration_quality": "ANCHORED",
        "share_count_quality": "POTENTIALLY_STALE",
        "ona_quality": "FORECAST_PARTIAL",
        "receivable_quality": "REPORTED",
        "option_quality": "FORECAST_MARK_TO_MARKET",
        "quality_notes": "partial forecast data using latest reported risk-free-rate/volatility",
    }

    assert _expected_between_reports(details) is True
    assert _dashboard_quality_reasons(details) == []


def test_estimated_status_between_reports_is_not_an_active_warning() -> None:
    details = {
        "data_status": "ESTIMATED",
        "cash_quality": "ANCHORED_ESTIMATE",
        "ona_quality": "INTERPOLATED",
        "option_quality": "INTERPOLATED_TO_REPORTED",
        "quality_notes": "interpolated between reported anchors",
    }

    assert _expected_between_reports(details) is True
    assert _dashboard_quality_reasons(details) == []


def test_high_cash_reconciliation_residual_remains_an_active_warning() -> None:
    details = {
        "data_status": "DEGRADED",
        "cash_quality": "FORECAST_PARTIAL",
        "cash_calibration_quality": "HIGH_RESIDUAL",
        "share_count_quality": "POTENTIALLY_STALE",
        "ona_quality": "FORECAST_PARTIAL",
    }

    reasons = _dashboard_quality_reasons(details)
    assert _expected_between_reports(details) is False
    assert len(reasons) == 1
    assert "høy avstemmingsrest" in reasons[0]


def test_gross_estimated_receivable_remains_an_active_warning() -> None:
    details = {
        "data_status": "ESTIMATED",
        "receivable_quality": "ESTIMATED_GROSS",
    }

    reasons = _dashboard_quality_reasons(details)
    assert len(reasons) == 1
    assert "Bemobi-fordring" in reasons[0]

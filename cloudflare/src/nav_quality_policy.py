"""Shared presentation policy for expected NAV estimates and actionable issues."""

from __future__ import annotations

from typing import Any


def _expected_between_reports(details: dict[str, Any]) -> bool:
    """Return True when lower-quality flags only describe normal between-report estimates."""
    data_status = str(details.get("data_status") or "").upper()
    cash_quality = str(details.get("cash_quality") or "").upper()
    cash_calibration_quality = str(
        details.get("cash_calibration_quality") or ""
    ).upper()
    share_count_quality = str(details.get("share_count_quality") or "").upper()
    ona_quality = str(details.get("ona_quality") or "").upper()
    receivable_quality = str(details.get("receivable_quality") or "").upper()
    option_quality = str(details.get("option_quality") or "").upper()
    notes = str(details.get("quality_notes") or "").lower()

    if data_status == "ESTIMATED":
        return True
    if data_status != "DEGRADED":
        return False

    actionable = (
        cash_calibration_quality == "HIGH_RESIDUAL"
        or receivable_quality == "ESTIMATED_GROSS"
        or "gross-estimated" in notes
    )
    expected_markers = (
        cash_quality in {"FORECAST_PARTIAL", "ANCHORED_ESTIMATE"}
        or share_count_quality == "POTENTIALLY_STALE"
        or ona_quality in {"FORECAST_PARTIAL", "INTERPOLATED"}
        or "partial forecast data" in notes
        or "interpolated between reported anchors" in notes
        or option_quality in {"INTERPOLATED_TO_REPORTED", "FORECAST_MARK_TO_MARKET"}
        or "latest reported risk-free-rate/volatility" in notes
    )
    return expected_markers and not actionable


def _dashboard_quality_reasons(details: dict[str, Any]) -> list[str]:
    """Expose actionable NAV-quality issues, not normal estimates between reports."""
    data_status = str(details.get("data_status") or "").upper()
    cash_calibration_quality = str(
        details.get("cash_calibration_quality") or ""
    ).upper()
    receivable_quality = str(details.get("receivable_quality") or "").upper()
    notes = str(details.get("quality_notes") or "").lower()

    reasons: list[str] = []
    if cash_calibration_quality == "HIGH_RESIDUAL":
        reasons.append(
            "Kontantestimatet ligger i en periode med høy avstemmingsrest og har lavere kvalitet."
        )
    if receivable_quality == "ESTIMATED_GROSS" or "gross-estimated" in notes:
        reasons.append(
            "Minst én Bemobi-fordring er bruttoestimert fordi det mangler et rapportankre i perioden."
        )

    if (
        data_status == "DEGRADED"
        and not reasons
        and not _expected_between_reports(details)
    ):
        reasons.append(
            "NAV-data har et kvalitetsavvik utover normal estimering mellom rapportdatoer."
        )

    return list(dict.fromkeys(reasons))

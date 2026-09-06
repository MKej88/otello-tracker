from __future__ import annotations

from src.bemobi_source_status import _result_release_status


def test_result_gap_is_healthy_when_previous_result_is_available() -> None:
    status, detail, uses_last_good = _result_release_status(
        {
            "status": "not_available",
            "reason": "result_documents_not_parseable",
        },
        {"fact_type": "RESULT", "fact_key": "2Q26"},
        "DEGRADED",
        "result documents not parseable",
        True,
    )

    assert status == "OK"
    assert "Ingen ny kvartalsrapport" in detail
    assert uses_last_good is False


def test_newer_result_parse_failure_still_warns() -> None:
    status, detail, uses_last_good = _result_release_status(
        {
            "status": "not_available",
            "reason": "newer_result_documents_not_parseable",
        },
        {"fact_type": "RESULT", "fact_key": "2Q26"},
        "DEGRADED",
        "newer result documents not parseable",
        True,
    )

    assert status == "DEGRADED"
    assert detail == "newer result documents not parseable"
    assert uses_last_good is True

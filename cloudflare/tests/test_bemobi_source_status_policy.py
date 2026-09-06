from __future__ import annotations

from src.bemobi_source_status import (
    _OperationalSourceDefinition,
    _operational_display_status,
    _result_release_status,
)


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


def test_otello_last_good_is_ok_without_health_status() -> None:
    source = _OperationalSourceDefinition(
        "otello_ir",
        "OTELLO_IR",
        "Otello IR",
        "Rapporter og selskapsinformasjon",
    )

    status, detail = _operational_display_status(
        source,
        {"fetched_at": "2026-08-20T08:00:00Z"},
    )

    assert status == "OK"
    assert detail is not None
    assert "ingen aktiv kildefeil" in detail


def test_other_source_remains_unknown_without_health_status() -> None:
    source = _OperationalSourceDefinition(
        "norges_bank",
        "NORGES_BANK",
        "Norges Bank",
        "Valutakurser",
    )

    status, detail = _operational_display_status(
        source,
        {"fetched_at": "2026-08-20T08:00:00Z"},
    )

    assert status == "UNKNOWN"
    assert detail == "Ingen kildekontroll er registrert ennå."


def test_otello_explicit_degraded_status_is_preserved() -> None:
    source = _OperationalSourceDefinition(
        "otello_ir",
        "OTELLO_IR",
        "Otello IR",
        "Rapporter og selskapsinformasjon",
    )

    status, detail = _operational_display_status(
        source,
        {
            "status": "DEGRADED",
            "fetched_at": "2026-08-20T08:00:00Z",
            "error_message": "Ufullstendig respons",
        },
    )

    assert status == "DEGRADED"
    assert detail == "Ufullstendig respons"


def test_otello_explicit_down_status_becomes_error() -> None:
    source = _OperationalSourceDefinition(
        "otello_ir",
        "OTELLO_IR",
        "Otello IR",
        "Rapporter og selskapsinformasjon",
    )

    status, detail = _operational_display_status(
        source,
        {
            "status": "DOWN",
            "fetched_at": "2026-08-20T08:00:00Z",
            "error_message": "Otello IR svarte ikke",
        },
    )

    assert status == "ERROR"
    assert detail == "Otello IR svarte ikke"

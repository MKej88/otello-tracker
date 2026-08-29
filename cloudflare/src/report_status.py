from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

REPORT_DOCUMENT_TYPE = "OTELLO_FINANCIAL_REPORT"
COST_DOCUMENT_TYPE = "ECONOMIC_NAV_COST_ANCHOR"
AUTO_REPORT_START_DATE = "2026-08-19"


def _metadata(raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(str(raw or "{}"))
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(Decimal(str(value)))
    except Exception:
        return None


def _delta(current: Any, previous: Any) -> float | None:
    current_value = _float(current)
    previous_value = _float(previous)
    if current_value is None or previous_value is None:
        return None
    return current_value - previous_value


async def _latest_report_document(repository) -> dict[str, Any] | None:
    return await repository.first(
        """
        SELECT id, title, url, published_at, fetched_at, metadata_json
        FROM source_documents
        WHERE document_type=?
        ORDER BY COALESCE(published_at, fetched_at) DESC, id DESC
        LIMIT 1
        """,
        (REPORT_DOCUMENT_TYPE,),
    )


async def _latest_result_news(repository) -> dict[str, Any] | None:
    return await repository.first(
        """
        SELECT headline, published_at, processing_status, summary, notes
        FROM company_news
        WHERE category='RESULTS'
          AND substr(COALESCE(published_at,''),1,10) >= ?
        ORDER BY COALESCE(published_at, created_at) DESC, id DESC
        LIMIT 1
        """,
        (AUTO_REPORT_START_DATE,),
    )


async def _news_for_message(repository, message_id: int | None) -> dict[str, Any] | None:
    if message_id is None:
        return None
    return await repository.first(
        """
        SELECT cn.headline, cn.published_at, cn.processing_status, cn.summary, cn.notes
        FROM company_news cn
        JOIN source_documents sd ON sd.id=cn.source_document_id
        WHERE cn.category='RESULTS'
          AND CAST(json_extract(sd.metadata_json, '$.newsweb_message_id') AS INTEGER)=?
        ORDER BY cn.id DESC LIMIT 1
        """,
        (message_id,),
    )


async def _previous_cash_anchor(repository, report_date: str) -> dict[str, Any] | None:
    return await repository.first(
        """
        SELECT as_of_date, reported_amount, reported_currency
        FROM cash_anchors
        WHERE anchor_type='REPORTED' AND as_of_date < ?
        ORDER BY as_of_date DESC, id DESC LIMIT 1
        """,
        (report_date,),
    )


async def _previous_ona_anchor(repository, report_date: str) -> dict[str, Any] | None:
    return await repository.first(
        """
        SELECT as_of_date, other_net_assets_reported, option_liability_reported
        FROM other_net_assets_reported_anchors
        WHERE as_of_date < ?
        ORDER BY as_of_date DESC, id DESC LIMIT 1
        """,
        (report_date,),
    )


async def _latest_cost_anchor(repository, report_date: str, *, before: bool) -> dict[str, Any] | None:
    operator = "<" if before else "="
    return await repository.first(
        f"""
        SELECT id, metadata_json
        FROM source_documents
        WHERE document_type=?
          AND json_extract(metadata_json, '$.scenario')='BASE'
          AND substr(json_extract(metadata_json, '$.effective_from'),1,10) {operator} ?
        ORDER BY substr(json_extract(metadata_json, '$.effective_from'),1,10) DESC, id DESC
        LIMIT 1
        """,
        (COST_DOCUMENT_TYPE, report_date),
    )


async def _report_nav_state(repository, report_date: str) -> dict[str, Any] | None:
    return await repository.first(
        """
        SELECT nav_scope, substr(as_of_at,1,10) AS nav_date, nav_per_share_nok,
               nav_total_nok, shares_outstanding, status
        FROM nav_snapshots
        WHERE substr(as_of_at,1,10) >= ?
        ORDER BY substr(as_of_at,1,10) DESC,
                 CASE nav_scope WHEN 'FULL' THEN 0 ELSE 1 END,
                 id DESC
        LIMIT 1
        """,
        (report_date,),
    )


async def report_status_summary(repository) -> dict[str, Any]:
    report = await _latest_report_document(repository)
    latest_news = await _latest_result_news(repository)
    if report is None:
        status = latest_news.get("processing_status") if latest_news else "WAITING"
        message = (
            "Resultatmelding funnet, men rapporten krever kontroll."
            if str(status).upper() == "REVIEW_REQUIRED"
            else "Venter på neste Otello-finansrapport."
        )
        return {
            "ready": False,
            "status": status,
            "headline": latest_news.get("headline") if latest_news else None,
            "published_at": latest_news.get("published_at") if latest_news else None,
            "message": message,
            "automation": {
                "newsweb_watch": True,
                "pdf_auto_download": True,
                "r2_archive": True,
                "strict_validation": True,
                "nav_rebuild": True,
            },
        }

    metadata = _metadata(report.get("metadata_json"))
    validation = metadata.get("validation") if isinstance(metadata.get("validation"), dict) else {}
    facts = metadata.get("facts") if isinstance(metadata.get("facts"), dict) else {}
    pdf = metadata.get("pdf") if isinstance(metadata.get("pdf"), dict) else {}
    parsed_r2 = metadata.get("parsed_r2") if isinstance(metadata.get("parsed_r2"), dict) else {}

    try:
        message_id = int(metadata.get("message_id")) if metadata.get("message_id") is not None else None
    except (TypeError, ValueError):
        message_id = None
    news = await _news_for_message(repository, message_id) or latest_news

    report_date = str(facts.get("report_date") or "")[:10] or None
    previous_cash = await _previous_cash_anchor(repository, report_date) if report_date else None
    previous_ona = await _previous_ona_anchor(repository, report_date) if report_date else None
    current_cost = await _latest_cost_anchor(repository, report_date, before=False) if report_date else None
    previous_cost = await _latest_cost_anchor(repository, report_date, before=True) if report_date else None
    nav_state = await _report_nav_state(repository, report_date) if report_date else None

    current_cost_meta = _metadata(current_cost.get("metadata_json")) if current_cost else {}
    previous_cost_meta = _metadata(previous_cost.get("metadata_json")) if previous_cost else {}

    current_cash = facts.get("cash_usd")
    previous_cash_usd = (
        previous_cash.get("reported_amount")
        if previous_cash and str(previous_cash.get("reported_currency") or "").upper() == "USD"
        else None
    )
    current_ona = facts.get("other_net_assets_usd")
    previous_ona_usd = previous_ona.get("other_net_assets_reported") if previous_ona else None
    current_option = facts.get("option_liability_usd")
    previous_option = previous_ona.get("option_liability_reported") if previous_ona else None
    current_opex = facts.get("recurring_opex_usd") or current_cost_meta.get("amount_usd")
    previous_opex = previous_cost_meta.get("amount_usd")

    apply_status = str(metadata.get("auto_apply_status") or "STAGED")
    processing_status = str(news.get("processing_status") if news else apply_status)
    issue_list = validation.get("issues") if isinstance(validation.get("issues"), list) else []
    validation_valid = validation.get("valid") is True
    pdf_archived = bool(pdf.get("r2_key"))
    parsed_archived = bool(parsed_r2.get("r2_key"))
    nav_rebuilt = bool(
        apply_status == "APPLIED"
        and nav_state is not None
        and report_date is not None
        and str(nav_state.get("nav_date") or "") >= report_date
    )

    return {
        "ready": True,
        "status": processing_status,
        "apply_status": apply_status,
        "headline": report.get("title") or (news.get("headline") if news else None),
        "published_at": report.get("published_at"),
        "fetched_at": report.get("fetched_at"),
        "report_date": report_date,
        "source_period": facts.get("source_period"),
        "parser_version": metadata.get("parser_version"),
        "source_url": report.get("url"),
        "report_document_id": report.get("id"),
        "message_id": message_id,
        "archive": {
            "pdf_archived": pdf_archived,
            "parsed_archived": parsed_archived,
            "pdf_key": pdf.get("r2_key"),
            "parsed_key": parsed_r2.get("r2_key"),
        },
        "validation": {
            "valid": validation_valid,
            "issue_count": len(issue_list),
            "issues": issue_list[:8],
            "policy": metadata.get("auto_apply_policy"),
        },
        "pipeline": {
            "newsweb_processed": news is not None,
            "pdf_downloaded": bool(pdf.get("content_sha256") or pdf_archived),
            "r2_archived": pdf_archived,
            "parsed": validation_valid,
            "anchors_applied": apply_status == "APPLIED",
            "nav_rebuilt": nav_rebuilt,
        },
        "changes": {
            "cash": {
                "previous_date": previous_cash.get("as_of_date") if previous_cash else None,
                "previous_usd": _float(previous_cash_usd),
                "current_usd": _float(current_cash),
                "delta_usd": _delta(current_cash, previous_cash_usd),
            },
            "other_net_assets": {
                "previous_date": previous_ona.get("as_of_date") if previous_ona else None,
                "previous_usd": _float(previous_ona_usd),
                "current_usd": _float(current_ona),
                "delta_usd": _delta(current_ona, previous_ona_usd),
            },
            "option_liability": {
                "previous_usd": _float(previous_option),
                "current_usd": _float(current_option),
                "delta_usd": _delta(current_option, previous_option),
            },
            "recurring_opex": {
                "previous_usd": _float(previous_opex),
                "current_usd": _float(current_opex),
                "delta_usd": _delta(current_opex, previous_opex),
            },
        },
        "nav": {
            "rebuilt": nav_rebuilt,
            "latest_date": nav_state.get("nav_date") if nav_state else None,
            "scope": nav_state.get("nav_scope") if nav_state else None,
            "nav_per_share_nok": _float(nav_state.get("nav_per_share_nok")) if nav_state else None,
            "status": nav_state.get("status") if nav_state else None,
            "exact_report_effect_per_share_nok": None,
            "effect_note": (
                "Eksakt før/etter-effekt kan først beregnes når et nytt rapportanker behandles med "
                "en lagret før-tilstand. Rapport-til-rapport-endringene over er kildebaserte og vises separat."
            ),
        },
        "summary": news.get("summary") if news else None,
        "notes": news.get("notes") if news else None,
    }

"""Conservative, redacted assessment of the latest Cloudflare fast refresh.

Raw provider messages and D1 metadata can contain URLs and sensitive information.
Only allowlisted step identifiers, result states and exception class names are
included in GitHub Actions output. Unknown partial failures stay critical.
"""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any

MAX_AGE = timedelta(minutes=100)
RUNNING_GRACE = timedelta(minutes=10)  # 8 minutes at incident #869; warn first, fail if stuck.
NON_CRITICAL_STEPS = frozenset({
    "dashboard_hot_snapshot",
    "investor_snapshots",
    "brazil_snapshot",
    "bemobi_translation",
})
_SAFE_CODE = re.compile(r"[A-Za-z0-9_.-]{1,80}\Z")


def safe_code(value: Any) -> str:
    """Allow only short code-like values in publicly readable workflow logs."""
    string = str(value or "")
    return string if _SAFE_CODE.fullmatch(string) else "unknown"


def _metadata(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    try:
        decoded = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def assess_fast_refresh(record: dict, *, now: datetime | None = None,
                        max_age: timedelta = MAX_AGE) -> dict:
    """Return OK, WARNING or FAILURE, with redacted step diagnostics."""
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    status = safe_code(str(record.get("status") or "").upper())
    if status in {"SUCCESS", "PARTIAL"} and not record.get("finished_at"):
        return {"severity": "FAILURE", "status": status, "age_minutes": None,
                "steps": [], "reason": "missing_completion_timestamp"}
    timestamp = record.get("finished_at") or record.get("started_at")
    if not timestamp:
        return {"severity": "FAILURE", "status": status, "age_minutes": None,
                "steps": [], "reason": "missing_timestamp"}
    try:
        last = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        if last.tzinfo is None:
            raise ValueError("timezone missing")
        age = now.astimezone(UTC) - last.astimezone(UTC)
    except (TypeError, ValueError, OverflowError):
        return {"severity": "FAILURE", "status": status, "age_minutes": None,
                "steps": [], "reason": "invalid_timestamp"}

    age_minutes = int(age.total_seconds() // 60)
    result = {"severity": "FAILURE", "status": status,
              "age_minutes": age_minutes, "steps": [], "reason": "unhealthy_status"}
    if not timedelta(0) <= age <= max_age:
        result["reason"] = "stale_or_future_refresh"
        return result

    metadata = _metadata(record.get("metadata_json"))
    errors = metadata.get("source_errors")
    if status == "SUCCESS":
        if isinstance(errors, list) and errors:
            result["reason"] = "success_with_source_errors"
            return result
        result.update(severity="OK", reason="healthy")
        return result

    if status != "PARTIAL":
        return result

    if not isinstance(errors, list) or not errors:
        result["reason"] = "partial_without_error_details"
        return result

    step_results = metadata.get("steps")
    if not isinstance(step_results, dict):
        step_results = {}
    allow_warning = True
    for error in errors:
        if not isinstance(error, dict):
            result["steps"].append({"step": "unknown", "type": "unknown",
                                    "status": "unknown"})
            allow_warning = False
            continue
        step = safe_code(error.get("step"))
        step_result = step_results.get(step)
        if not isinstance(step_result, dict):
            step_result = {}
        result["steps"].append({
            "step": step,
            "type": safe_code(error.get("error_type")),
            "status": safe_code(step_result.get("status")),
        })
        if not (step in NON_CRITICAL_STEPS
                and step_result.get("non_critical") is True):
            allow_warning = False

    nav = step_results.get("dirty_nav")
    if not isinstance(nav, dict) or nav.get("status") != "ok":
        allow_warning = False
    if allow_warning:
        result.update(severity="WARNING", reason="confirmed_noncritical_steps")
    else:
        result["reason"] = "critical_or_unclassified_partial"
    return result


def assess_fast_refresh_window(records: list[dict], *,
                               now: datetime | None = None,
                               max_age: timedelta = MAX_AGE) -> dict:
    """Check latest and previous completed runs without hiding a stuck RUNNING job.

    A current RUNNING row is temporarily a warning only when it is recent and
    the immediately preceding *completed* job is independently fresh and
    either healthy or has only explicitly confirmed non-critical errors.
    UNKNOWN, FAILED, stale, missing metadata, or overlong RUNNING remains fatal.
    """
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    if not records:
        return {"severity": "FAILURE", "status": "MISSING", "age_minutes": None,
                "steps": [], "reason": "missing_fast_jobs"}

    latest = records[0]
    if str(latest.get("status") or "").upper() != "RUNNING":
        return assess_fast_refresh(latest, now=now, max_age=max_age)

    report = {"severity": "FAILURE", "status": "RUNNING",
              "age_minutes": None, "steps": [],
              "reason": "running_without_healthy_previous",
              "previous_status": "MISSING", "previous_age_minutes": None}
    if latest.get("finished_at"):
        report["reason"] = "running_with_completion_timestamp"
        return report
    started_at = latest.get("started_at")
    try:
        start = datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
        if start.tzinfo is None:
            raise ValueError("timezone missing")
        elapsed = now.astimezone(UTC) - start.astimezone(UTC)
    except (TypeError, ValueError, OverflowError):
        report["reason"] = "invalid_running_timestamp"
        return report
    report["age_minutes"] = int(elapsed.total_seconds() // 60)
    if elapsed < timedelta(0):
        report["reason"] = "future_running_timestamp"
        return report
    if elapsed >= RUNNING_GRACE:
        report["reason"] = "running_exceeded_grace"
        return report

    # Never skip a FAILED completed job to find an older successful job.
    previous = next(
        (row for row in records[1:]
         if str(row.get("status") or "").upper() != "RUNNING"), None
    )
    if previous is None:
        return report
    previous_result = assess_fast_refresh(previous, now=now, max_age=max_age)
    report["previous_status"] = previous_result["status"]
    report["previous_age_minutes"] = previous_result["age_minutes"]
    if previous_result["severity"] == "WARNING" and previous_result["reason"] == "confirmed_noncritical_steps":
        # Preserve the secondary warning and its sanitized evidence during the next run.
        report.update(severity="WARNING", reason="recent_running_with_noncritical_previous",
                      steps=previous_result["steps"])
        return report
    if previous_result["severity"] != "OK":
        report["reason"] = "previous_completed_unhealthy"
        return report
    report.update(severity="WARNING", reason="recent_running_with_healthy_previous")
    return report


# Only fixed categories and counts leave D1; never expose document URLs or error text.
TRANSLATION_ERROR_GROUPS_SQL = """
SELECT CASE
    WHEN translation_error LIKE 'value_validation:%' OR translation_error LIKE 'verdikontroll feilet%' THEN 'value_validation'
    WHEN translation_error LIKE '%originaldokument HTTP %' THEN 'document_http'
    WHEN translation_error LIKE '%krever OCR%' THEN 'pdf_without_text'
    WHEN translation_error LIKE 'download:%' THEN 'document_download'
    WHEN translation_error LIKE 'pdf_extraction:%' THEN 'pdf_extraction'
    WHEN translation_error LIKE 'translation:%' THEN 'ai_translation'
    WHEN translation_error LIKE 'summary:%' THEN 'ai_summary'
    WHEN translation_error LIKE 'archive:%' THEN 'archive'
    WHEN translation_error LIKE '%model%not found%' OR translation_error LIKE '%model%deprecated%'
         OR translation_error LIKE '%model%does not exist%' OR translation_error LIKE '%model%not available%' THEN 'ai_model'
    WHEN translation_error LIKE '%JsException%' OR translation_error LIKE '%PyProxy%' THEN 'runtime_binding'
    WHEN translation_error LIKE '%Workers AI%' OR translation_error LIKE '%JSON%' THEN 'ai_response'
    WHEN translation_error LIKE '%Maksimalt antall behandlingsforsøk%' THEN 'interrupted_exhausted'
    ELSE 'other'
END AS reason,
COUNT(*) AS document_count,
SUM(CASE WHEN translation_attempts >= 3 THEN 1 ELSE 0 END) AS exhausted_count
FROM source_documents sd JOIN sources s ON s.id=sd.source_id
WHERE s.code IN ('CVM','BEMOBI_IR')
  AND sd.translation_status IN ('FAILED','PENDING') AND sd.translation_error IS NOT NULL
GROUP BY 1 ORDER BY 1
"""


def public_fast_refresh_warning(record: dict, *, now: datetime, max_age: timedelta) -> dict | None:
    """Only confirmed secondary failures may narrow the public impact description."""
    report = assess_fast_refresh(record, now=now, max_age=max_age)
    if report["reason"] != "confirmed_noncritical_steps":
        return None
    steps = sorted({item["step"] for item in report["steps"]})
    payload: dict[str, Any] = {"steps": steps}
    if "bemobi_translation" in steps:
        translation = _metadata(record.get("metadata_json"))["steps"]["bemobi_translation"]
        queue = translation.get("queue")
        if isinstance(queue, dict):
            counts = {key: queue[key] for key in ("failed", "exhausted", "overdue")
                      if type(queue.get(key)) is int and queue[key] >= 0}
            failed = translation.get("failed")
            if type(failed) is int and failed >= 0:
                counts["failed_this_run"] = failed
            payload["translation_queue"] = counts
    return payload


# A bounded read-only listing of unresolved IDs, source codes and sanitized HTTP status.
# Legacy errors are classified inside D1; raw exception messages never leave the query.
TRANSLATION_DOCUMENTS_SQL = """
SELECT document_id, source, attempts, status,
       CASE
         WHEN translation_error LIKE 'claim:%' THEN 'claim'
         WHEN translation_error LIKE 'download:%' OR translation_error LIKE 'originaldokument HTTP %' THEN 'download'
         WHEN translation_error LIKE 'deduplication:%' THEN 'deduplication'
         WHEN translation_error LIKE 'pdf_extraction:%' OR translation_error LIKE '%krever OCR%' THEN 'pdf_extraction'
         WHEN translation_error LIKE 'translation:%' THEN 'translation'
         WHEN translation_error LIKE 'value_validation:%' OR translation_error LIKE 'verdikontroll feilet%' THEN 'value_validation'
         WHEN translation_error LIKE 'summary:%' THEN 'summary'
         WHEN translation_error LIKE 'archive:%' THEN 'archive'
         WHEN translation_error LIKE 'database_write:%' THEN 'database_write'
         WHEN translation_error LIKE '%PyProxy%' OR translation_error LIKE '%JsException%'
              OR translation_error LIKE '%Cannot read properties%' OR translation_error LIKE '%object has no attribute%'
              OR translation_error LIKE '%not JSON serializable%' THEN 'legacy_runtime'
         WHEN translation_error LIKE '%model%not found%' OR translation_error LIKE '%model%deprecated%'
              OR translation_error LIKE '%model%does not exist%' THEN 'legacy_model'
         WHEN translation_error LIKE '%Workers AI%' THEN 'legacy_ai'
         ELSE 'unknown' END AS stage,
       CASE
         WHEN translation_error LIKE 'translation:%Dokumentet overskrider sikker behandlingsgrense%' THEN 'max_document_chunks'
         WHEN translation_error LIKE '%verdikontroll feilet%' THEN 'missing_values'
         WHEN translation_error LIKE '%krever OCR%' THEN 'ocr_required'
         WHEN translation_error LIKE '%WorkersAIError%' THEN 'ai_error'
         ELSE 'other_or_unknown' END AS safe_reason,
       CASE WHEN instr(translation_error, 'ai_code=') > 0
            THEN CAST(substr(translation_error, instr(translation_error, 'ai_code=') + length('ai_code='), 4) AS INTEGER)
            ELSE NULL END AS ai_code,
       CASE WHEN instr(translation_error, 'originaldokument HTTP ') > 0
            THEN CAST(substr(translation_error, instr(translation_error, 'originaldokument HTTP ') + length('originaldokument HTTP '), 3) AS INTEGER)
            ELSE NULL END AS http
FROM (
    SELECT sd.id AS document_id, s.code AS source, sd.translation_attempts AS attempts,
           sd.translation_status AS status, sd.translation_error
    FROM source_documents sd JOIN sources s ON s.id=sd.source_id
    WHERE s.code IN ('CVM','BEMOBI_IR') AND sd.translation_status IN ('FAILED','PENDING')
      AND sd.translation_error IS NOT NULL
    ORDER BY sd.id DESC LIMIT 30
) AS recent
ORDER BY document_id DESC
"""

# Reduced evidence when D1 rejects the detailed query. Never fetch raw errors.
TRANSLATION_DOCUMENTS_FALLBACK_SQL = """
SELECT sd.id AS document_id, s.code AS source,
       sd.translation_attempts AS attempts, sd.translation_status AS status,
       CASE
         WHEN sd.translation_error LIKE 'value_validation:%'
              OR sd.translation_error LIKE 'verdikontroll feilet%' THEN 'value_validation'
         WHEN sd.translation_error LIKE '%originaldokument HTTP %'
              OR sd.translation_error LIKE 'download:%' THEN 'download'
         WHEN sd.translation_error LIKE '%krever OCR%'
              OR sd.translation_error LIKE 'pdf_extraction:%' THEN 'pdf_extraction'
         WHEN sd.translation_error LIKE 'translation:%' THEN 'translation'
         WHEN sd.translation_error LIKE 'summary:%' THEN 'summary'
         ELSE 'unknown' END AS stage
FROM source_documents sd JOIN sources s ON s.id=sd.source_id
WHERE s.code IN ('CVM','BEMOBI_IR')
  AND sd.translation_status IN ('FAILED','PENDING') AND sd.translation_error IS NOT NULL
ORDER BY sd.id DESC LIMIT 30
"""

_AI_CODES = frozenset({3003, 3006, 3007, 3008, 3023, 3036, 3039, 3040, 3041, 3042,
                       5004, 5005, 5007, 5016, 5018, 5019, 5028, 5035})
_AI_CATEGORIES = frozenset({"invalid_request", "request_too_large", "timeout", "account_access",
                            "quota", "capacity", "model_unavailable", "provider_error",
                            "binding_error", "invalid_response", "empty_response", "truncated",
                            "probe_validation"})


def _ai_error_label(info: Any) -> str:
    if not isinstance(info, dict):
        return "-"
    code = info.get("code")
    http = info.get("http")
    category = _known(info.get("category"), _AI_CATEGORIES)
    code_label = str(code) if type(code) is int and code in _AI_CODES else "-"
    http_label = str(http) if type(http) is int and 400 <= http <= 599 else "-"
    return f"{category} / kode {code_label} / HTTP {http_label}"


_TRANSLATION_MODELS = frozenset({"@cf/google/gemma-4-26b-a4b-it", "@cf/meta/llama-3.1-8b-instruct"})
_TRANSLATION_STAGES = frozenset({"claim", "download", "deduplication", "pdf_extraction", "translation",
                                 "value_validation", "summary", "archive", "database_write",
                                 "legacy_runtime", "legacy_model", "legacy_ai", "unknown"})


def _known(value: Any, options) -> str:
    return value if isinstance(value, str) and value in options else "unknown"


def _count(value: Any) -> str:
    return str(value) if type(value) is int and 0 <= value <= 1_000_000_000 else "-"


def render_translation_diagnostics(record: dict | None, unresolved: list[dict], *,
                                   documents_available: bool = True) -> list[str]:
    """Only fixed enums and integer counters may enter the Actions report."""
    steps = _metadata((record or {}).get("metadata_json")).get("steps")
    translation = steps.get("bemobi_translation") if isinstance(steps, dict) else None
    lines = ["", "## Oversettelse: siste kjøring og dokumentdiagnose", ""]
    if not isinstance(translation, dict):
        lines.append("- Ingen registrert oversettelsesmetadata for siste kjøring.")
    else:
        model = _known(translation.get("model"), _TRANSLATION_MODELS)
        lines.append(f"- Modell konfigurert i kjøringen: {model} (ikke i seg selv bevis på AI-kall)")
        lines.append(f"- Valgt / fullført / feilet: {_count(translation.get('selected'))} / {_count(translation.get('completed'))} / {_count(translation.get('failed'))}")
        probe = translation.get("ai_probe")
        if isinstance(probe, dict):
            lines.append(f"- AI-produksjonstest: {_known(probe.get('status'), {'ok', 'error', 'not_run'})}; "
                         f"binding-kall: {_count(probe.get('binding_calls'))}; feil: {_ai_error_label(probe.get('error'))}")
        diagnostics = translation.get("diagnostics")
        if not isinstance(diagnostics, list):
            lines.append("- Trinnvis måling mangler (eldre kjøring). AI-kall kan ikke bekreftes.")
        else:
            lines.extend(["", "| Dokument-ID | Kilde | Trinn | Resultat | Nedlastingsforsøk | AI-kall (adapter / binding / svar) |",
                          "|---:|---|---|---|---|---|"])
            for item in diagnostics[:20]:
                if not isinstance(item, dict):
                    continue
                downloads = item.get("downloads")
                attempts = []
                for attempt in downloads[:4] if isinstance(downloads, list) else []:
                    if not isinstance(attempt, dict):
                        continue
                    route = _known(attempt.get("route"), {"original", "official_alternative", "verified_r2", "queue_r2", "normalized_r2"})
                    result = _known(attempt.get("result"), {"ok", "http_error", "not_pdf", "error"})
                    code = _count(attempt.get("http")) if type(attempt.get("http")) is int and 100 <= attempt["http"] <= 599 else "-"
                    attempts.append(f"{route}: {result} (HTTP {code})")
                binding = _count(item.get("ai_binding_calls")) if item.get("native_binding") is True else "-"
                lines.append(f"| {_count(item.get('document_id'))} | {_known(item.get('source'), {'CVM', 'BEMOBI_IR'})} | "
                             f"{_known(item.get('stage'), _TRANSLATION_STAGES)} | {_known(item.get('outcome'), {'ready', 'reused', 'not_required', 'error', 'progress'})} | "
                             f"{'; '.join(attempts) or '-'} | {_count(item.get('ai_provider_calls'))} / {binding} / {_count(item.get('ai_responses'))} |")
            for item in diagnostics[:20]:
                if not isinstance(item, dict):
                    continue
                if isinstance(item.get("ai_error"), dict):
                    lines.extend(["", f"- AI-feil dokument {_count(item.get('document_id'))}: {_ai_error_label(item['ai_error'])}"])
                if "summary_error" in item:
                    code = _known(item["summary_error"], {"invalid_json", "not_object", "invalid_title",
                                                          "invalid_summary", "duplicate_field",
                                                          "unexpected_fields", "size_or_type"})
                    lines.extend(["", f"- Sammendragsfeil dokument {_count(item.get('document_id'))}: {code}"])
                if "source_chunks" in item:
                    lines.append(f"- Dokument {_count(item.get('document_id'))}: "
                                 f"{_count(item.get('source_characters'))} tegn / {_count(item.get('source_chunks'))} deler; "
                                 f"grense: {_known(item.get('translation_limit'), {'max_document_chunks'})}")
                if "value_missing_count" in item or "value_chunk_retries" in item:
                    lines.append(f"- Verdikontroll dokument {_count(item.get('document_id'))}: "
                                 f"{_count(item.get('value_chunk_retries'))} nye delforsøk; "
                                 f"{_count(item.get('value_missing_count'))} manglende verdier")
                if "parts_total" in item:
                    lines.append(f"- Dokument {_count(item.get('document_id'))}: "
                                 f"{_count(item.get('parts_saved'))} nye verifiserte deler, "
                                 f"{_count(item.get('parts_reused'))} gjenbrukte, "
                                 f"{_count(item.get('parts_total'))} totalt")
                if "value_chunk_splits" in item:
                    lines.append(f"- Dokument {_count(item.get('document_id'))}: "
                                 f"{_count(item.get('value_chunk_splits'))} oppdelinger etter verdikontroll")
                if "translation_checkpoint" in item:
                    state = _known(item["translation_checkpoint"], {"miss", "saved", "reused", "write_failed", "progress"})
                    lines.extend(["", f"- Mellomlagret oversettelse dokument {_count(item.get('document_id'))}: {state}"])
            if not diagnostics:
                lines.append("- Ingen dokumenter ble behandlet i denne kjøringen.")
    if not documents_available:
        lines.extend(["", "### Uavklarte dokumenter",
                      "- IKKE BEKREFTET: dokumentlisten kunne ikke hentes fra D1."])
        return lines
    lines.extend(["", "### Uavklarte dokumenter (maks 30)", "",
                  "| Dokument-ID | Kilde | Status | Forsøk | Feiltrinn | HTTP |", "|---:|---|---|---:|---|---:|"])
    for row in unresolved[:30]:
        if not isinstance(row, dict):
            continue
        http = row.get("http")
        lines.append(f"| {_count(row.get('document_id'))} | {_known(row.get('source'), {'CVM', 'BEMOBI_IR'})} | "
                     f"{_known(row.get('status'), {'FAILED', 'PENDING'})} | {_count(row.get('attempts'))} | "
                     f"{_known(row.get('stage'), _TRANSLATION_STAGES)} | {_count(http) if type(http) is int and 100 <= http <= 599 else '-'} |")
    for row in unresolved[:30]:
        if isinstance(row, dict) and row.get("safe_reason") in {"max_document_chunks", "missing_values", "ocr_required", "ai_error"}:
            lines.append(f"- Feilårsak dokument {_count(row.get('document_id'))}: {row['safe_reason']}")
        if isinstance(row, dict) and type(row.get("ai_code")) is int and row["ai_code"] in _AI_CODES:
            lines.append(f"- Workers AI-feilkode for dokument {_count(row.get('document_id'))}: {row['ai_code']}")
    return lines

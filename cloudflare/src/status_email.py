from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

try:
    from .nav_quality_policy import expected_dashboard_quality
    from .status_email_report import (
        dashboard_url,
        operational_lines,
        oslo_time,
        render_html,
        safe_detail,
    )
except ImportError:
    from nav_quality_policy import expected_dashboard_quality
    from status_email_report import (
        dashboard_url,
        operational_lines,
        oslo_time,
        render_html,
        safe_detail,
    )

_STATUS_LABELS = {
    "SUCCESS": "OK",
    "PARTIAL": "DELVIS",
    "FAILED": "FEILET",
}

_SOURCE_LABELS = {
    "NORGES_BANK": "Norges Bank",
    "YAHOO_FINANCE": "Life360 / Yahoo Finance",
    "B3": "B3",
    "CVM": "CVM",
    "BEMOBI_IR": "Bemobi IR",
    "NEWSWEB": "NewsWeb",
    "EURONEXT": "Euronext / OTEC",
}


def _env_text(env: Any, name: str) -> str:
    try:
        value = getattr(env, name, None)
    except (AttributeError, TypeError):
        return ""
    return str(value or "").strip()


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=parsed.tzinfo or UTC)
    except ValueError:
        return None


def _duration_label(started_at: str | None, finished_at: str | None) -> str | None:
    started = _parse_time(started_at)
    finished = _parse_time(finished_at)
    if started is None or finished is None:
        return None
    seconds = max(0, int((finished - started).total_seconds()))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours} t {minutes} min {seconds} sek"
    if minutes:
        return f"{minutes} min {seconds} sek"
    return f"{seconds} sek"


def _number(value: Any, digits: int = 2) -> str | None:
    if value is None:
        return None
    try:
        return f"{float(value):.{digits}f}".replace(".", ",")
    except (TypeError, ValueError):
        return None


def _count(value: Any) -> str | None:
    return f"{value:,}".replace(",", " ") if type(value) is int and value >= 0 else None


def _resource_rows(result: dict[str, Any]) -> list[tuple[str, str]]:
    """Only use already collected metrics, never infer job totals from partial steps."""
    rows = []
    records = _count(result.get("records_written"))
    if records is not None:
        rows.append(("Registrerte datapunkter", records))
    sources = result.get("source_results") or {}
    metrics = [
        item["repository"] for item in sources.values()
        if isinstance(item, dict) and isinstance(item.get("repository"), dict)
        and _count(item["repository"].get("d1_rows_read")) is not None
        and _count(item["repository"].get("d1_rows_written")) is not None
        and type(item["repository"].get("d1_operations")) is int
        and item["repository"]["d1_operations"] > 0
        and item["repository"].get("d1_row_meta_operations") == item["repository"]["d1_operations"]
    ]
    if metrics:
        read = _count(sum(item["d1_rows_read"] for item in metrics))
        written = _count(sum(item["d1_rows_written"] for item in metrics))
        rows.append(("D1 – målte kildesteg (ikke totalt)",
                     f"{len(metrics)} steg: {read} rader lest / {written} skrevet"))
    translation = sources.get("bemobi_translation") or {}
    counts = []
    for key, label in (("completed", "ferdigbehandlet"), ("deferred", "videreføres"), ("failed", "feilet")):
        value = _count(translation.get(key))
        if value is not None:
            counts.append(f"{value} {label}")
    if counts:
        rows.append(("Dokumentbehandling i natt", " · ".join(counts)))
    queue = translation.get("queue") or {}
    counts = []
    for key, label in (("pending", "venter"), ("processing", "behandles"), ("failed", "feilet"),
                       ("exhausted", "uten flere forsøk"), ("overdue", "forsinket")):
        value = _count(queue.get(key))
        if value is not None:
            counts.append(f"{value} {label}")
    if counts:
        rows.append(("Oversettelseskø", " · ".join(counts)))
    diagnostics = translation.get("diagnostics")
    if isinstance(diagnostics, list) and diagnostics:
        for key, label in (("ai_provider_calls", "AI-kall i dokumentbehandling"),
                           ("parts_reused", "Gjenbrukte oversettelsesdeler"),
                           ("summary_checkpoints_reused", "Gjenbrukte sammendrag")):
            values = [item[key] for item in diagnostics
                      if isinstance(item, dict) and _count(item.get(key)) is not None]
            if values:
                rows.append((label, _count(sum(values)) + " (rapportert)"))
    archive = result.get("archive") or {}
    if str(archive.get("status")).lower() == "ok":
        size = _count(archive.get("compressed_bytes"))
        chunks = _count(archive.get("chunk_count"))
        if size is not None and chunks is not None:
            rows.append(("R2-snapshot", f"{chunks} deler · {size} komprimerte byte"))
    elif archive.get("reason") == "weekly_or_month_end_only":
        rows.append(("R2-snapshot", "Ikke planlagt (søndag og månedsslutt)"))
    return rows


def build_status_email(
    result: dict[str, Any],
    *,
    economic: dict[str, Any] | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
    public_url: str = "",
) -> dict[str, str]:
    # Apply the dashboard's quality policy to the email only; retain raw job data.
    preflight = result.get("preflight") or {}
    warnings = preflight.get("warnings") or []
    actionable_warnings = []
    model_information = (
        result.get("status") == "SUCCESS"
        and preflight.get("ready") is True
        and not preflight.get("blockers")
        and not result.get("critical_errors")
        and any(
            item.get("name") == "dashboard_quality"
            and item.get("status") == "PASS"
            and (item.get("details") or {}).get("classification") == "MODEL_INFO"
            for item in preflight.get("checks") or []
            if isinstance(item, dict)
        )
    )
    for warning in warnings:
        details = warning.get("details") if isinstance(warning, dict) else None
        if (
            isinstance(warning, dict)
            and warning.get("name") == "dashboard_quality"
            and warning.get("status") == "WARN"
            and isinstance(details, dict)
            and result.get("status") == "SUCCESS"
            and preflight.get("ready") is True
            and not preflight.get("blockers")
            and not result.get("critical_errors")
            and expected_dashboard_quality(details, critical_checks_passed=True)
        ):
            model_information = True
        else:
            actionable_warnings.append(warning)
    result = (
        {**result, "preflight": {**preflight, "warnings": actionable_warnings}}
        if preflight
        else result
    )

    raw_status = str(result.get("status") or "FAILED").upper()
    status = _STATUS_LABELS.get(raw_status, raw_status)
    target_date = str(result.get("target_date") or "ukjent dato")
    subject = f"Otello Tracker – nattkjøring {status} – {target_date}"

    source_health = result.get("source_health") or {}
    source_count = len(source_health)
    source_ok = sum(1 for value in source_health.values() if str(value).upper() == "OK")
    duration = _duration_label(started_at, finished_at)

    report: dict[str, Any] = {}
    details, incidents = operational_lines(result, presentation=report)
    report_status = "OK med avvik" if raw_status == "SUCCESS" and incidents else status
    lines = [
        "Otello Tracker – nattstatus",
        "",
        f"Status: {report_status}",
        f"Datadato: {target_date}",
    ]
    if started_at:
        lines.append(f"Startet: {oslo_time(started_at)}")
    if finished_at:
        lines.append(f"Fullført: {oslo_time(finished_at)}")
    if duration:
        lines.append(f"Kjøretid: {duration}")
    if result.get("job_id") is not None:
        lines.append(f"Jobb-ID: {result['job_id']}")
    if source_count:
        exceptions = [
            f"{_SOURCE_LABELS.get(str(code), str(code))}: {str(health).upper()}"
            for code, health in source_health.items() if str(health).upper() != "OK"
        ]
        lines.append(f"Datakilder: {source_ok}/{source_count} OK"
                     + (" – " + "; ".join(exceptions) if exceptions else ""))
    else:
        lines.append("Datakilder: ikke bekreftet")

    report.update(date=safe_detail(target_date), duration=duration,
                  source_counts=(source_ok, source_count),
                  sources=[(safe_detail(_SOURCE_LABELS.get(str(code), str(code))), safe_detail(health).upper())
                           for code, health in source_health.items()],
                  timing=[(label, safe_detail(value)) for label, value in (
                      ("Startet", oslo_time(started_at) if started_at else None),
                      ("Fullført", oslo_time(finished_at) if finished_at else None),
                      ("Jobb-ID", result.get("job_id")),
                  ) if value is not None],
                  resources=_resource_rows(result), model_information=model_information,
                  nav={"metrics": []})

    # Put actual failures and consequences ahead of normal checks and market numbers.
    lines.extend(details)
    preflight = result.get("preflight") or {}
    if preflight:
        ready = "OK" if preflight.get("ready") is True else "FEILET" if preflight.get("ready") is False else "ikke rapportert"
        report["preflight"] = (ready, len(preflight.get("blockers") or []), len(preflight.get("warnings") or []))
        lines.extend(["", f"Preflight: {ready} · Blokkeringer: {len(preflight.get('blockers') or [])} · Advarsler: {len(preflight.get('warnings') or [])}"])
    if model_information:
        lines.append("Modellinformasjon: normal estimering mellom rapportdatoene.")

    economic = economic or {}
    if raw_status != "FAILED" and economic.get("ready"):
        nav = _number(economic.get("nav_per_share"), 2)
        discount = _number(economic.get("discount_pct"), 1)
        lines.extend(["", "Investor-NAV (sist tilgjengelig):"])
        if nav is not None:
            lines.append(f"- Økonomisk NAV: {nav} kr/aksje")
            report["nav"]["metrics"].append(("Økonomisk NAV", f"{nav} kr"))
        if discount is not None:
            lines.append(f"- Rabatt: {discount} %")
            report["nav"]["metrics"].append(("NAV-rabatt", f"{discount} %"))
        conservative = _number(economic.get("conservative_nav_per_share"), 2)
        if conservative is not None:
            lines.append(f"- Konservativ NAV: {conservative} kr/aksje")
            report["nav"]["metrics"].append(("Konservativ NAV", f"{conservative} kr"))
        if not report["nav"]["metrics"]:
            report["nav"]["reason"] = "NAV-nøkkeltall ikke rapportert."
        if economic.get("as_of_date"):
            lines.append(f"- NAV-dato: {safe_detail(economic['as_of_date'])}")
            report["nav"]["date"] = safe_detail(economic["as_of_date"])
    else:
        reason = "ikke bekreftet i denne kjøringen" if raw_status == "FAILED" else safe_detail(economic.get("reason") or "ikke tilgjengelig")
        lines.extend(["", f"Investor-NAV: ikke klar ({reason})"])
        report["nav"]["reason"] = f"Investor-NAV: ikke klar ({reason})"

    if report["resources"]:
        lines.extend(["", "Ressursforbruk og dokumenter:",
                      *[f"- {label}: {value}" for label, value in report["resources"]]])

    if incidents and raw_status == "SUCCESS":
        subject = f"Otello Tracker – nattkjøring OK med avvik – {target_date}"
    clean_url = dashboard_url(public_url)
    if clean_url:
        lines.extend(["", f"Dashboard: {clean_url}/"])
        if clean_url == "https://otellotracker.com":
            lines.append("Produksjonsdiagnose: https://github.com/MKej88/otello-tracker/issues/164")
            lines.append("Kjørelogger: https://github.com/MKej88/otello-tracker/actions")

    lines.extend(["", "Automatisk statusmelding fra Otello Tracker."])
    text = "\n".join(lines)
    return {
        "subject": subject,
        "text": text,
        "html": render_html(
            status=status, incidents=incidents, public_url=clean_url, report=report
        ),
    }


async def _finalize_failed_job(env: Any, result: dict[str, Any]) -> dict[str, Any]:
    """Best-effort close a raw Workflow exception so public runtime never stays RUNNING."""
    if str(result.get("status") or "").upper() != "FAILED":
        return {"status": "skipped", "reason": "not_failed"}
    if "source_results" in result:
        return {"status": "skipped", "reason": "already_finalized"}
    job_id = result.get("job_id")
    if job_id is None:
        return {"status": "skipped", "reason": "missing_job_id"}

    try:
        from performance_repository import PerformanceD1WriteRepository

        repository = PerformanceD1WriteRepository(env.DB)
        errors = result.get("critical_errors") or result.get("errors") or []
        message_parts: list[str] = []
        for item in errors[:5]:
            if isinstance(item, dict):
                message_parts.append(
                    str(item.get("error") or item.get("step") or "workflow failed")
                )
            else:
                message_parts.append(str(item))
        error_message = "; ".join(message_parts)[:4000] or "Cloudflare Workflow failed"
        finished_at = (
            datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        )
        await repository.finish_job(
            int(job_id),
            finished_at=finished_at,
            status="FAILED",
            records_written=int(result.get("records_written") or 0),
            error_message=error_message,
            metadata={
                "phase": "16.3",
                "target_date": result.get("target_date"),
                "workflow_exception": True,
                "critical_errors": errors[:10],
            },
        )
        return {"status": "finalized", "finished_at": finished_at}
    except Exception as exc:
        return {
            "status": "error",
            "error": str(exc)[:500],
            "error_type": type(exc).__name__,
        }


async def send_full_refresh_status_email(
    env: Any, result: dict[str, Any]
) -> dict[str, Any]:
    """Finalize failure state and send one best-effort status email when configured."""
    finalization = await _finalize_failed_job(env, result)

    recipient = _env_text(env, "STATUS_EMAIL_TO")
    sender = _env_text(env, "STATUS_EMAIL_FROM")
    public_url = _env_text(env, "PUBLIC_URL")
    try:
        binding = getattr(env, "STATUS_EMAIL", None)
    except (AttributeError, TypeError):
        binding = None

    if not recipient or not sender or binding is None:
        return {
            "status": "skipped",
            "reason": "not_configured",
            "job_finalization": finalization,
        }

    economic: dict[str, Any] = {"ready": False, "reason": "ikke hentet"}
    started_at = None
    finished_at = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")

    try:
        from economic_nav_investor import economic_nav_summary
        from performance_repository import PerformanceD1Repository

        repository = PerformanceD1Repository(env.DB)
        if str(result.get("status") or "").upper() != "FAILED":
            try:
                economic = await economic_nav_summary(repository)
            except Exception as exc:
                economic = {
                    "ready": False,
                    "reason": f"NAV-oppsummering feilet: {type(exc).__name__}",
                }

        job_id = result.get("job_id")
        if job_id is not None:
            timing = await repository.first(
                "SELECT started_at, finished_at FROM job_runs WHERE id=? LIMIT 1",
                (int(job_id),),
            )
            if timing:
                started_at = timing.get("started_at")
                finished_at = timing.get("finished_at") or finished_at
    except Exception as exc:
        economic = {
            "ready": False,
            "reason": f"statusgrunnlag feilet: {type(exc).__name__}",
        }

    message = build_status_email(
        result,
        economic=economic,
        started_at=started_at,
        finished_at=finished_at,
        public_url=public_url,
    )

    try:
        from js import Object
        from pyodide.ffi import to_js as _to_js

        payload = _to_js(
            {
                "to": recipient,
                "from": {"email": sender, "name": "Otello Tracker"},
                "subject": message["subject"],
                "text": message["text"],
                "html": message["html"],
            },
            dict_converter=Object.fromEntries,
        )
        response = await binding.send(payload)
        message_id = getattr(response, "messageId", None)
        return {
            "status": "sent",
            "message_id": str(message_id) if message_id is not None else None,
            "job_finalization": finalization,
        }
    except Exception as exc:
        return {
            "status": "error",
            "error": str(exc)[:500],
            "error_type": type(exc).__name__,
            "job_finalization": finalization,
        }

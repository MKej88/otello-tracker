from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

_STATUS_LABELS = {
    "SUCCESS": "OK",
    "PARTIAL": "DELVIS",
    "FAILED": "FEILET",
}

_SOURCE_LABELS = {
    "NORGES_BANK": "Norges Bank",
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
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
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


def build_status_email(
    result: dict[str, Any],
    *,
    economic: dict[str, Any] | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
    public_url: str = "",
) -> dict[str, str]:
    raw_status = str(result.get("status") or "FAILED").upper()
    status = _STATUS_LABELS.get(raw_status, raw_status)
    target_date = str(result.get("target_date") or "ukjent dato")
    subject = f"Otello Tracker – nattkjøring {status} – {target_date}"

    source_health = result.get("source_health") or {}
    source_count = len(source_health)
    source_ok = sum(1 for value in source_health.values() if str(value).upper() == "OK")
    duration = _duration_label(started_at, finished_at)

    lines = [
        "Otello Tracker – nattstatus",
        "",
        f"Status: {status}",
        f"Datadato: {target_date}",
    ]
    if duration:
        lines.append(f"Kjøretid: {duration}")
    lines.append(f"Oppdaterte datapunkter: {int(result.get('records_written') or 0)}")
    if source_count:
        lines.append(f"Datakilder: {source_ok}/{source_count} OK")

    if source_health:
        lines.extend(["", "Datakilder:"])
        for code, health in source_health.items():
            label = _SOURCE_LABELS.get(str(code), str(code))
            lines.append(f"- {label}: {str(health).upper()}")

    preflight = result.get("preflight") or {}
    if preflight:
        ready = "OK" if preflight.get("ready") else "FEILET"
        blockers = len(preflight.get("blockers") or [])
        warnings = len(preflight.get("warnings") or [])
        lines.extend(
            [
                "",
                "Datakontroll:",
                f"- Preflight: {ready}",
                f"- Blokkeringer: {blockers}",
                f"- Advarsler: {warnings}",
            ]
        )

    economic = economic or {}
    if economic.get("ready"):
        nav = _number(economic.get("nav_per_share"), 2)
        discount = _number(economic.get("discount_pct"), 1)
        conservative_nav = _number(economic.get("conservative_nav_per_share"), 2)
        lines.extend(["", "Investor-NAV:"])
        if nav is not None:
            lines.append(f"- Økonomisk NAV: {nav} kr/aksje")
        if discount is not None:
            lines.append(f"- Rabatt: {discount} %")
        if conservative_nav is not None:
            lines.append(f"- Konservativ NAV: {conservative_nav} kr/aksje")
        if economic.get("as_of_date"):
            lines.append(f"- NAV-dato: {economic['as_of_date']}")
    else:
        reason = str(economic.get("reason") or "ikke tilgjengelig")
        lines.extend(["", f"Investor-NAV: ikke klar ({reason})"])

    errors = result.get("critical_errors") or result.get("errors") or []
    if errors:
        lines.extend(["", "Feil / avvik:"])
        for item in errors[:5]:
            if isinstance(item, dict):
                step = str(item.get("step") or "ukjent steg")
                error = str(item.get("error") or "ukjent feil")
                lines.append(f"- {step}: {error[:500]}")
            else:
                lines.append(f"- {str(item)[:500]}")

    clean_url = public_url.strip().rstrip("/")
    if clean_url:
        lines.extend(["", f"Dashboard: {clean_url}/"])

    lines.extend(["", "Automatisk statusmelding fra Otello Tracker."])
    return {"subject": subject, "text": "\n".join(lines)}


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
                message_parts.append(str(item.get("error") or item.get("step") or "workflow failed"))
            else:
                message_parts.append(str(item))
        error_message = "; ".join(message_parts)[:4000] or "Cloudflare Workflow failed"
        finished_at = datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
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


async def send_full_refresh_status_email(env: Any, result: dict[str, Any]) -> dict[str, Any]:
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
        try:
            economic = await economic_nav_summary(repository)
        except Exception as exc:
            economic = {"ready": False, "reason": f"NAV-oppsummering feilet: {type(exc).__name__}"}

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
        economic = {"ready": False, "reason": f"statusgrunnlag feilet: {type(exc).__name__}"}

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

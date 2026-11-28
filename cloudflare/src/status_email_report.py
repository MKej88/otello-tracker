"""Email-safe presentation of completed nightly results; no additional data writes."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from html import escape
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

try:
    from .nav_quality_policy import _dashboard_quality_reasons
except ImportError:
    from nav_quality_policy import _dashboard_quality_reasons


def safe_detail(value: object) -> str:
    text = (
        json.dumps(value, ensure_ascii=False)
        if isinstance(value, (dict, list))
        else str(value)
    )
    text = re.sub(r"(?i)(bearer\s+)\S+", r"\1[skjult]", text)
    text = re.sub(
        r"(?i)((?:token|api[_-]?key|password|secret|authorization)[\s\"\x27]*[:=][\s\"\x27]*)[^\s,;\"\x27&}]+",
        r"\1[skjult]",
        text,
    )
    return " ".join(text.split())[:600]


def oslo_time(value: str | None) -> str:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return (
            parsed.replace(tzinfo=parsed.tzinfo or UTC)
            .astimezone(ZoneInfo("Europe/Oslo"))
            .strftime("%d.%m.%Y kl. %H:%M %Z")
        )
    except (ValueError, TypeError):
        return "ikke tilgjengelig"


def dashboard_url(value: str) -> str:
    try:
        parsed = urlsplit(value.strip())
    except ValueError:
        return ""
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        return ""
    return value.strip().rstrip("/")


def _guidance(step: str, error: str) -> str:
    value = f"{step} {error}".lower()
    if "lease lost" in value or "writer lock" in value or "writer lease" in value:
        return "Kontroller skrivelås og aktiv Workflow-instans før ny kjøring."
    if "memory limit" in value or "memoryerror" in value:
        return "Kontroller minnefeil og omkjøringer i Workflow-diagnosen."
    if step == "BEMOBI_IR" and "offisiell resultatrapport verifisert" in value:
        return "Følg opp rapportfeeden; rapportdekning er verifisert via alternativ kilde."
    if "429" in value or "too many" in value or "rate limit" in value:
        return "En forespørselsgrense kan være nådd. Kontroller kjøreloggen og begrens samtidige oppslag før ny kjøring."
    if "timeout" in value or "timed out" in value or "unavailable" in value:
        return "Datakilden kan være midlertidig utilgjengelig. Kontroller kilde og siste datadato før ny kjøring."
    if "401" in value or "403" in value or "unauthorized" in value:
        return "Tilgang kan være avvist. Kontroller tokenets rettigheter og utløpsdato."
    if step == "bemobi_translation":
        return "Kontroller oversettelseskøen og dokumentfeil; maksimalt tre automatiske forsøk per dokument."
    if step == "dashboard_hot_snapshot":
        return "Cacheoppdateringen er ikke bekreftet. Nettsiden kan vise eldre data; kontroller cache og API etter ny oppdatering."
    if step == "archive":
        return "Arkiveringen er ikke bekreftet. Kontroller R2-tilgang og at nattens sikkerhetskopi finnes."
    if step == "estimated_nav_history":
        return "NAV-historikken kan være ufullstendig. Kontroller historikkjobben og kjør manglende perioder på nytt."
    if step in {"nav", "preflight"}:
        return "Nye NAV-tall er ikke fullt bekreftet. Kontroller datagrunnlag og blokkeringer før tallene brukes."
    return "Kontroller steget i kjøreloggen og siste datadato. Vurder ny kjøring når årsaken er avklart."


def _incident_detail(value: object) -> str:
    """Prefer the actual exception or structured reason, not a traceback dump."""
    if isinstance(value, dict):
        name = value.get("name") or value.get("step") or ""
        detail = value.get("error") or value.get("reason") or value.get("details")
        if isinstance(detail, dict):
            evidence = []
            for key, item in detail.items():
                if isinstance(item, (str, int, float, bool)) and key not in {"quality_notes", "traceback"}:
                    evidence.append(f"{key}={safe_detail(item)[:120]}")
            detail = ", ".join(evidence[:6])
        return safe_detail(f"{name}: {detail}" if detail else name or "Årsak ikke oppgitt")
    raw = str(value)
    if "Traceback (most recent call last)" in raw:
        causes = re.findall(
            r"(?:RuntimeError|MemoryError|TimeoutError|ValueError|TypeError|OSError):\s*([^\n]+)",
            raw,
        )
        if causes:
            return safe_detail(causes[-1])
        if "Worker exceeded memory limit" in raw:
            return "Worker exceeded memory limit"
    return safe_detail(raw)


def operational_lines(result: dict) -> tuple[list[str], int]:
    checks_summary: list[str] = []
    incidents: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def incident(step: str, detail: object) -> None:
        item = (step, _incident_detail(detail))
        if item not in seen:
            seen.add(item)
            incidents.append(item)

    for key in ("critical_errors", "errors"):
        for item in result.get(key) or []:
            if isinstance(item, dict):
                incident(
                    str(item.get("step") or "ukjent steg"), item.get("error") or item
                )
            else:
                incident("ukjent steg", item)
    for key, label in (
        ("nav", "NAV-beregning"),
        ("dashboard_hot_snapshot", "Dashboard-cache"),
        ("estimated_nav_history", "NAV-historikk"),
        ("archive", "R2-arkivering"),
        ("investor_snapshots", "Investor-cache"),
    ):
        data = result.get(key) or {}
        status = str(data.get("status") or "ikke rapportert").lower()
        if key == "estimated_nav_history" and "complete" in data:
            period_cache = data.get("period_cache") or {}
            retry = data.get("retry") or {}
            pending = retry.get("pending")
            if data.get("complete") is True and period_cache.get("status") == "ok" and not pending:
                status = "ok"
            elif data.get("complete") is False or period_cache.get("status") in {"partial", "error", "failed"} or pending:
                status = "partial"
            else:
                status = "ikke rapportert"
            if status == "partial":
                parts = []
                if data.get("complete") is False:
                    parts.append(f"historikk: {data.get('stop_reason') or 'ikke fullført'}")
                if period_cache.get("status") in {"partial", "error", "failed"}:
                    parts.append(f"periodecache: {period_cache.get('written', 0)}/6")
                    for failure in (period_cache.get("failures") or period_cache.get("period_failures") or [])[:6]:
                        parts.append(f"{failure.get('period_key') or 'periode'}: {_incident_detail(failure.get('reason') or failure)}")
                if pending:
                    parts.append(f"{pending} historikkpunkter venter på nytt forsøk")
                    if retry.get("attempted") is not None:
                        parts.append(f"behandlet {retry['attempted']}, løst {retry.get('written', 0)} i natt")
                    for failure in (retry.get("failures") or [])[:3]:
                        parts.append(f"{safe_detail(failure.get('date') or '-')}: {_incident_detail(failure.get('reason') or 'ukjent årsak')}")
                if parts:
                    incident(key, "; ".join(parts))
            parked = retry.get("parked_before_cost_anchor") or 0
            if parked:
                checks_summary.append(f"NAV-historikk: {parked} datoer før kostnadsdekning ({safe_detail(retry.get('first_base_anchor') or '-')}); avventer eldre dokumentert anker")
            if period_cache.get("status") == "ok" and period_cache.get("written") == 6:
                checks_summary.append("Periodecache: 6/6")
        if key == "investor_snapshots":
            for component, detail in (data.get("components") or {}).items():
                if detail.get("status") in {"error", "partial", "failed", "skipped"}:
                    incident(key, f"{component}: {detail.get('error') or detail.get('error_type') or detail.get('reason') or detail.get('status')}")
        translated = {
            "ok": "OK",
            "success": "OK",
            "error": "FEILET",
            "partial": "DELVIS",
            "skipped": "HOPPET OVER",
        }.get(status, status)
        checks_summary.append(f"{label}: {translated}")
        if data.get("error") or status in {"error", "partial", "failed", "not_ready"}:
            if not any(name == key for name, _ in incidents):
                incident(key, data.get("error") or data.get("reason") or status)

    preflight = result.get("preflight") or {}
    checks = preflight.get("checks") or []
    if checks:
        passed = sum(item.get("status") == "PASS" for item in checks)
        checks_summary.append(f"Datakontroller bestått: {passed}/{len(checks)}")
    for key, label in (("blockers", "Blokkering"), ("warnings", "Advarsel")):
        for item in preflight.get(key) or []:
            if isinstance(item, dict) and item.get("name") == "dashboard_quality":
                details = item.get("details") or {}
                quality = safe_detail(details.get("data_status") or "ukjent")
                evidence = ", ".join(
                    f"{key}={safe_detail(details[key])}"
                    for key in (
                        "as_of_date", "model_scope", "cash_quality",
                        "cash_calibration_quality", "share_count_quality",
                        "ona_quality", "receivable_quality", "option_quality",
                    )
                    if details.get(key)
                )
                incident(
                    "preflight",
                    f"{label}: NAV-datakvalitet {quality} (dashboard_quality). "
                    + (" ".join(_dashboard_quality_reasons(details)) + " "
                       if _dashboard_quality_reasons(details) else
                       "Årsaken må bekreftes i produksjonsdiagnosen. ")
                    + (f"Grunnlag: {evidence}. " if evidence else "")
                    + "Statusen alene påviser ikke feil i NAV-beregningen.",
                )
            else:
                incident("preflight", f"{label}: {_incident_detail(item)}")
    source_results = result.get("source_results") or {}
    bemobi = source_results.get("bemobi_web") or {}
    ir_news = bemobi.get("ir_news") or {}
    # This flag is set by the merger only when it was otherwise OK and the
    # official quarterly release is verified. Do not infer a common cause
    # from two generic partial/degraded labels.
    shared_report_feed = (
        bemobi.get("status") == "partial"
        and bemobi.get("report_feed_warning_non_blocking") is True
        and bemobi.get("non_blocking_degraded") is True
        and ir_news.get("status") == "ok"
        and ir_news.get("report_feed_status") not in {None, "ok", "retired"}
        and not bemobi.get("error")
        and (result.get("source_health") or {}).get("BEMOBI_IR") == "DEGRADED"
        and all(
            (bemobi.get(key) or {}).get("status") in {"ok", "skipped"}
            for key in ("distribution_ingestion", "distribution_cash", "result_release")
        )
        and (bemobi.get("ir") or {}).get("status") == "ok"
    )
    for step, data in source_results.items():
        status = str(data.get("status") or "ikke rapportert")
        if step == "bemobi_web":
            if shared_report_feed:
                period = (data.get("result_release") or {}).get("period")
                period_text = f" ({safe_detail(period)})" if period else ""
                incident("BEMOBI_IR", "Rapportfeed returnerer ingen rapporter; "
                         f"offisiell resultatrapport verifisert{period_text}. "
                         "Utdelingsinnlesing er kontrollert.")
                continue
            if data.get("report_coverage_warning"):
                release = data.get("result_release") or {}
                discovery = release.get("cvm_live_discovery") or {}
                detail = discovery.get("error") or release.get("error") or release.get("reason") or "ukjent årsak"
                incident(step, f"Resultatrapport: CVM-rapportdekning ikke bekreftet; {_incident_detail(detail)}")
            # Show independent substep issues rather than a list of healthy steps.
            for key, label in (
                ("ir", "IR-fakta"), ("ir_news", "IR-meldinger"),
                ("result_release", "Resultatrapport"),
                ("distribution_ingestion", "Utdelingsinnlesing"),
                ("distribution_cash", "Utdelingsoppgjør"),
            ):
                sub = data.get(key) or {}
                if sub.get("error") or str(sub.get("status")).lower() in {
                    "error", "partial", "failed", "not_available", "review_required",
                }:
                    incident(step, f"{label}: {_incident_detail(sub.get('error') or sub.get('reason') or sub.get('status'))}")
                elif key == "ir_news" and sub.get("report_feed_status") not in {None, "ok", "retired"}:
                    incident(step, f"IR-rapportfeed: {safe_detail(sub['report_feed_status'])}")
            if any(name == step for name, _ in incidents) and not data.get("error"):
                continue
        if data.get("error") or status.lower() in {
            "error",
            "partial",
            "failed",
            "not_available",
            "review_required",
        }:
            incident(step, data.get("error") or data.get("reason") or status)
    for source, health in (result.get("source_health") or {}).items():
        if source == "BEMOBI_IR" and shared_report_feed:
            continue
        if str(health).upper() != "OK":
            incident(str(source), f"Kildestatus: {health}")

    if not incidents and str(result.get("status") or "FAILED").upper() != "SUCCESS":
        incident(
            "workflow",
            "Kjøringen er ikke bekreftet fullført; detaljert feilårsak mangler i resultatet.",
        )
    lines = ["", f"Avvik og oppfølging ({len(incidents)}):"]
    if not incidents:
        lines.append(
            "Ingen rapporterte feil eller advarsler i mottatte kjøringsresultater."
        )
    actions = []
    for step, detail in incidents[:10]:
        lines.append(f"- {step}: {detail}")
        action = _guidance(step, detail)
        if action not in actions:
            actions.append(action)
    if len(incidents) > 10:
        lines.append(f"Ytterligere {len(incidents) - 10} avvik finnes i kjøreloggen.")
    if actions:
        lines.extend(["", "Anbefalt oppfølging:", *[f"- {action}" for action in actions]])
    lines.extend(["", "Kontrollstatus:", " · ".join(checks_summary)])
    lines.extend(["", "Separate GitHub-kontroller inngår ikke i denne statusen. Ikke rapportert = ikke bekreftet."])
    return lines, len(incidents)


def render_html(text: str, *, status: str, incidents: int, public_url: str) -> str:
    color = (
        "#b42318"
        if status == "FEILET"
        else "#b54708"
        if incidents or status != "OK"
        else "#067647"
    )
    blocks = text.split("\n\n")
    sections = []
    for block in blocks[1:-1]:
        rows = block.splitlines()
        if not rows:
            continue
        if rows[0].startswith("Dashboard:"):
            continue
        title = (
            rows.pop(0)
            if rows[0].endswith(":")
            else "Oppsummering"
            if not sections
            else "Status"
        )
        content = ""
        for row in rows:
            label, separator, value = row.removeprefix("- ").partition(": ")
            if separator and title.startswith("Avvik og oppfølging"):
                # A single full-width cell avoids cramped, unbreakable technical labels
                # on iPhone/Outlook while retaining the exact diagnostic text.
                display_label = {"estimated_nav_history": "NAV-historikk",
                                 "preflight": "Datakontroll"}.get(label, label)
                content += (
                    f'<tr><td colspan="2" style="padding:10px 0;border-bottom:1px solid #eef2f6;word-break:break-word;overflow-wrap:anywhere">'
                    f'<div style="font-weight:bold;margin-bottom:4px">{escape(display_label)}</div>'
                    f'<div>{escape(value)}</div></td></tr>'
                )
            elif separator:
                content += f'<tr><td style="padding:5px 8px 5px 0;border-bottom:1px solid #eef2f6;vertical-align:top;width:30%">{escape(label)}</td><td style="padding:5px 0;border-bottom:1px solid #eef2f6;overflow-wrap:anywhere">{escape(value)}</td></tr>'
            else:
                content += f'<tr><td colspan="2" style="padding:5px 0;overflow-wrap:anywhere">{escape(row)}</td></tr>'
        sections.append(
            f'<h2 style="font-size:17px;margin:18px 0 6px;color:#172b4d">{escape(title.rstrip(":"))}</h2><table role="presentation" width="100%" cellspacing="0" cellpadding="0">{content}</table>'
        )
    url = dashboard_url(public_url)
    button = (
        f'<p style="margin:28px 0"><a href="{escape(url, quote=True)}/" style="background:#172b4d;color:white;padding:13px 20px;text-decoration:none;border-radius:6px;display:inline-block">Åpne Otello Tracker</a></p>'
        if url
        else ""
    )
    if url == "https://otellotracker.com":
        button += ('<p style="margin:12px 0"><a href="https://github.com/MKej88/otello-tracker/issues/164">Produksjonsdiagnose</a>'
                   ' · <a href="https://github.com/MKej88/otello-tracker/actions">Kjørelogger</a></p>')
    badge = f"{status} · {incidents} rapporterte avvik" if incidents else status
    return (
        '<!doctype html><html lang="nb"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>'
        '<body style="margin:0;background:#f2f5f9;font-family:Arial,Helvetica,sans-serif;color:#344054;font-size:14px;line-height:1.5">'
        '<table role="presentation" width="100%" cellspacing="0" cellpadding="0"><tr><td align="center" style="padding:24px 12px">'
        '<table role="presentation" width="640" cellspacing="0" cellpadding="0" style="width:100%;max-width:640px;background:#fff;border:1px solid #e4e7ec;border-radius:10px">'
        '<tr><td style="background:#172b4d;color:#fff;padding:18px 20px"><div style="font-size:12px;letter-spacing:2px">OTELLO TRACKER</div><h1 style="margin:8px 0 0;font-size:26px">Nattrapport</h1></td></tr>'
        f'<tr><td style="padding:18px 20px"><p style="color:{color};font-size:18px;font-weight:bold;margin:0">{escape(badge)}</p>'
        + "".join(sections)
        + button
        + '<p style="font-size:12px;color:#667085;margin-top:24px">Automatisk statusmelding fra Otello Tracker. Tidspunkter vises i norsk tid.</p></td></tr></table></td></tr></table></body></html>'
    )

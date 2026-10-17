"""Email-safe presentation of completed nightly results; no additional data writes."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from html import escape
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo


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
    if "429" in value or "too many" in value or "rate limit" in value:
        return "En forespørselsgrense kan være nådd. Kontroller kjøreloggen og begrens samtidige oppslag før ny kjøring."
    if "timeout" in value or "timed out" in value or "unavailable" in value:
        return "Datakilden kan være midlertidig utilgjengelig. Kontroller kilde og siste datadato før ny kjøring."
    if "401" in value or "403" in value or "unauthorized" in value:
        return "Tilgang kan være avvist. Kontroller tokenets rettigheter og utløpsdato."
    if step == "dashboard_hot_snapshot":
        return "Cacheoppdateringen er ikke bekreftet. Nettsiden kan vise eldre data; kontroller cache og API etter ny oppdatering."
    if step == "archive":
        return "Arkiveringen er ikke bekreftet. Kontroller R2-tilgang og at nattens sikkerhetskopi finnes."
    if step == "estimated_nav_history":
        return "NAV-historikken kan være ufullstendig. Kontroller historikkjobben og kjør manglende perioder på nytt."
    if step in {"nav", "preflight"}:
        return "Nye NAV-tall er ikke fullt bekreftet. Kontroller datagrunnlag og blokkeringer før tallene brukes."
    return "Kontroller steget i kjøreloggen og siste datadato. Vurder ny kjøring når årsaken er avklart."


def operational_lines(result: dict) -> tuple[list[str], int]:
    lines = [
        "",
        "Kjøringsdetaljer:",
        f"- Jobb-ID: {result.get('job_id') or 'ikke tilgjengelig'}",
    ]
    incidents: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def incident(step: str, detail: object) -> None:
        item = (step, safe_detail(detail))
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
    ):
        data = result.get(key) or {}
        status = str(data.get("status") or "ikke rapportert").lower()
        translated = {
            "ok": "OK",
            "success": "OK",
            "error": "FEILET",
            "partial": "DELVIS",
            "skipped": "HOPPET OVER",
        }.get(status, status)
        lines.append(f"- {label}: {translated}")
        if data.get("generated_at"):
            lines.append(f"- Cache generert: {oslo_time(data['generated_at'])}")
        if data.get("reason"):
            lines.append(f"- {label}, begrunnelse: {safe_detail(data['reason'])}")
        if data.get("error") or status in {"error", "partial", "failed", "not_ready"}:
            incident(key, data.get("error") or data.get("reason") or status)

    preflight = result.get("preflight") or {}
    checks = preflight.get("checks") or []
    if checks:
        passed = sum(item.get("status") == "PASS" for item in checks)
        lines.append(f"- Datakontroller bestått: {passed}/{len(checks)}")
    for key, label in (("blockers", "Blokkering"), ("warnings", "Advarsel")):
        for item in preflight.get(key) or []:
            incident("preflight", f"{label}: {safe_detail(item)}")
    for step, data in (result.get("source_results") or {}).items():
        status = str(data.get("status") or "ikke rapportert")
        counts = [
            f"{label}: {data[key]}"
            for key, label in (
                ("rows_written", "lagrede rader"),
                ("archived", "arkiverte"),
                ("applied", "anvendte"),
                ("review_required", "til gjennomgang"),
            )
            if isinstance(data.get(key), (int, float))
        ]
        lines.append(
            f"- Kildesteg {step}: {status}"
            + (f" ({', '.join(counts)})" if counts else "")
        )
        if data.get("error") or status.lower() in {
            "error",
            "partial",
            "failed",
            "not_available",
            "review_required",
        }:
            incident(step, data.get("error") or data.get("reason") or status)
    for source, health in (result.get("source_health") or {}).items():
        if str(health).upper() != "OK":
            incident(str(source), f"Kildestatus: {health}")

    if not incidents and str(result.get("status") or "FAILED").upper() != "SUCCESS":
        incident(
            "workflow",
            "Kjøringen er ikke bekreftet fullført; detaljert feilårsak mangler i resultatet.",
        )
    lines.extend(["", "Feil, advarsler og oppfølging:"])
    if not incidents:
        lines.append(
            "Ingen rapporterte feil eller advarsler i mottatte kjøringsresultater."
        )
    for step, detail in incidents[:15]:
        lines.extend(
            [f"- {step}: {detail}", f"  Oppfølging: {_guidance(step, detail)}"]
        )
    if len(incidents) > 15:
        lines.append(f"Ytterligere {len(incidents) - 15} avvik finnes i kjøreloggen.")
    lines.extend(
        [
            "",
            "Kontrollomfang:",
            "Rapporten viser resultatene fra denne nattkjøringen. Ikke rapportert betyr at kontrollen ikke er bekreftet.",
            "Separate GitHub-kontroller av produksjon, NAV og cache kjøres senere og inngår ikke i denne mailens status.",
        ]
    )
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
            if separator:
                content += f'<tr><td style="padding:8px 12px 8px 0;border-bottom:1px solid #eef2f6;vertical-align:top;width:42%">{escape(label)}</td><td style="padding:8px 0;border-bottom:1px solid #eef2f6;overflow-wrap:anywhere">{escape(value)}</td></tr>'
            else:
                content += f'<tr><td colspan="2" style="padding:8px 0;overflow-wrap:anywhere">{escape(row)}</td></tr>'
        sections.append(
            f'<h2 style="font-size:17px;margin:25px 0 10px;color:#172b4d">{escape(title.rstrip(":"))}</h2><table role="presentation" width="100%" cellspacing="0" cellpadding="0">{content}</table>'
        )
    url = dashboard_url(public_url)
    button = (
        f'<p style="margin:28px 0"><a href="{escape(url, quote=True)}/" style="background:#172b4d;color:white;padding:13px 20px;text-decoration:none;border-radius:6px;display:inline-block">Åpne Otello Tracker</a></p>'
        if url
        else ""
    )
    badge = f"{status} · {incidents} rapporterte avvik" if incidents else status
    return (
        '<!doctype html><html lang="nb"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>'
        '<body style="margin:0;background:#f2f5f9;font-family:Arial,Helvetica,sans-serif;color:#344054;font-size:14px;line-height:1.5">'
        '<table role="presentation" width="100%" cellspacing="0" cellpadding="0"><tr><td align="center" style="padding:24px 12px">'
        '<table role="presentation" width="640" cellspacing="0" cellpadding="0" style="width:100%;max-width:640px;background:#fff;border:1px solid #e4e7ec;border-radius:10px">'
        '<tr><td style="background:#172b4d;color:#fff;padding:28px"><div style="font-size:12px;letter-spacing:2px">OTELLO TRACKER</div><h1 style="margin:8px 0 0;font-size:26px">Nattrapport</h1></td></tr>'
        f'<tr><td style="padding:24px 28px"><p style="color:{color};font-size:18px;font-weight:bold;margin:0">{escape(badge)}</p>'
        + "".join(sections)
        + button
        + '<p style="font-size:12px;color:#667085;margin-top:24px">Automatisk statusmelding fra Otello Tracker. Tidspunkter vises i norsk tid.</p></td></tr></table></td></tr></table></body></html>'
    )

"""Read-only follow-up for NAV history backlog and source-documented receivables."""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal, InvalidOperation

# Keep the diagnostics independent of Worker bindings. These are the active
# calculation versions; the wiring regression test checks the source constants.
HISTORY_VERSION = "ESTIMATED_NAV_V1"
FULL_VERSION = "full-market-nav-daily-v2"
MAX_DETAIL_ROWS = 300
COVERAGE_REASONS = frozenset({"missing_estimated_nav_anchor", "before_cost_anchor"})
REASONS = frozenset({
    "missing_full_nav_row", "missing_option_inputs", "missing_reported_cash_anchor",
    "missing_estimated_nav_anchor", "before_cost_anchor", "cash_fx_not_ready", "invalid_share_count",
    "missing_bemobi_receivable", "missing_bemobi_attribution_inputs",
    "bemobi_holding_changed", "bemobi_attribution_does_not_reconcile",
    "missing_period_operating_cost_inputs", "invalid_interest_income_anchor",
    "invalid_interest_income_anchor_period", "missing_interest_income_fx_segments",
    "invalid_interest_income_fx_segment", "interest_income_fx_segments_do_not_cover_overlap",
    "missing_other_cash_residual_after_operating_cost_split",
    "missing_other_cash_or_share_count", "bemobi_paid_split_does_not_reconcile",
    "bemobi_receivable_split_does_not_reconcile", "not_ready",
})


def followup_queries() -> list[dict]:
    # Unknown upstream error strings never enter the report.
    codes = ",".join("'" + code + "'" for code in sorted(REASONS))
    reason = f"CASE WHEN reason IN ({codes}) THEN reason ELSE 'OTHER' END"
    return [
        {"sql": f"""SELECT {reason} AS reason_code, COUNT(*) AS count,
                   MIN(date) AS first_date, MAX(date) AS last_date,
                   MIN(first_failed_at) AS first_failed_at,
                   MAX(attempts) AS max_attempts,
                   SUM(CASE WHEN next_retry_at <= strftime('%Y-%m-%dT%H:%M:%fZ','now')
                            THEN 1 ELSE 0 END) AS due,
                   CASE WHEN {reason} IN ('missing_estimated_nav_anchor','before_cost_anchor')
                   THEN json_group_array(json_array(date, CASE WHEN next_retry_at <=
                        strftime('%Y-%m-%dT%H:%M:%fZ','now') THEN 1 ELSE 0 END))
                   ELSE NULL END AS coverage_dates
                   FROM estimated_nav_history_retry_queue
                   WHERE calculation_version=? GROUP BY reason_code ORDER BY count DESC""",
         "params": [HISTORY_VERSION]},
        {"sql": f"""SELECT date, {reason} AS reason_code, attempts,
                   substr(first_failed_at,1,10) AS first_failed_date,
                   substr(last_failed_at,1,10) AS last_failed_date,
                   substr(next_retry_at,1,10) AS next_retry_date
                   FROM estimated_nav_history_retry_queue WHERE calculation_version=?
                   ORDER BY next_retry_at, date LIMIT {MAX_DETAIL_ROWS}""",
         "params": [HISTORY_VERSION]},
        {"sql": """SELECT o.estimate_date, o.receivable_quality,
                   o.associated_receivable_nok,
                   json_extract(c.value,'$.corporate_action_id') AS modeled_action_id,
                   json_extract(c.value,'$.holding_shares') AS holding_shares,
                   json_extract(c.value,'$.brl_nok') AS brl_nok,
                   json_extract(c.value,'$.amount_nok') AS modeled_amount_nok,
                   ca.id AS action_id, ca.action_type, ca.ex_date, ca.payment_date,
                   ca.amount_per_share AS gross_per_share, ca.net_amount_per_share,
                   ca.withholding_rate, ca.tax_treatment, ca.source_document_id
                   FROM other_net_assets_daily_estimates o
                   LEFT JOIN json_each(CASE WHEN json_valid(o.receivable_components_json)
                       THEN o.receivable_components_json ELSE '[]' END) c ON 1=1
                   LEFT JOIN corporate_actions ca
                       ON ca.id=json_extract(c.value,'$.corporate_action_id')
                   WHERE o.estimate_date=(
                       SELECT substr(as_of_at,1,10) FROM nav_snapshots
                       WHERE nav_scope='FULL' AND calculation_version=?
                       ORDER BY as_of_at DESC,id DESC LIMIT 1
                   )
                   ORDER BY ca.id LIMIT 50""", "params": [FULL_VERSION]},
    ]


def cost_anchor_query() -> dict:
    # Select only the metadata fields used by the economic NAV cost model.
    return {"sql": """SELECT id AS document_id,
                json_extract(metadata_json,'$.scenario') AS scenario,
                json_extract(metadata_json,'$.effective_from') AS effective_from,
                json_extract(metadata_json,'$.amount_usd') AS amount_usd,
                json_extract(metadata_json,'$.period_days') AS period_days
                FROM source_documents
                WHERE document_type='ECONOMIC_NAV_COST_ANCHOR'
                AND json_valid(metadata_json)
                ORDER BY published_at DESC,id DESC"""}


def _date(value) -> str:
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except (ValueError, TypeError):
        return "-"


def _number(value) -> Decimal | None:
    try:
        n = Decimal(str(value))
        return n if n.is_finite() and abs(n) < Decimal("1e18") else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def _fmt(value) -> str:
    n = _number(value)
    return format(n, "f") if n is not None else "-"


def _reason(value) -> str:
    return value if value in REASONS else "OTHER"


def _choice(value, allowed) -> str:
    return value if value in allowed else "UKJENT"


def earliest_base_cost_anchor(cost_anchors: list[dict]) -> str | None:
    return min((
        day for row in cost_anchors
        if str(row.get("scenario") or "").upper() == "BASE"
        and (day := _date(row.get("effective_from"))) != "-"
        and (amount := _number(row.get("amount_usd"))) is not None and amount >= 0
        and (days := _number(row.get("period_days"))) is not None
        and days > 0 and days == days.to_integral_value()
    ), default=None)


def _coverage_counts(row: dict, first_base: str | None) -> tuple[int, int]:
    """Only documented pre-anchor dates are parked, never other failure reasons."""
    if not first_base or row.get("reason_code") not in COVERAGE_REASONS:
        return 0, 0
    if _date(row.get("last_date")) != "-" and _date(row["last_date"]) < first_base:
        return int(row["count"]), int(row["due"])
    try:
        entries = json.loads(row.get("coverage_dates") or "[]")
        if len(entries) != int(row["count"]):
            return 0, 0
        if any(not isinstance(item, list) or len(item) != 2
               or _date(item[0]) == "-" or item[1] not in (0, 1) for item in entries):
            return 0, 0
        parked = [item for item in entries if _date(item[0]) < first_base]
        return len(parked), sum(item[1] for item in parked)
    except (TypeError, ValueError, KeyError):
        return 0, 0


def assess_followup(groups: list[dict], details: list[dict], receivables: list[dict],
                    *, preflight: dict, cost_anchors: list[dict] | None = None) -> dict:
    total = sum(int(r["count"]) for r in groups)
    total_due = sum(int(r["due"]) for r in groups)
    first_base = earliest_base_cost_anchor(cost_anchors or [])
    coverage = [_coverage_counts(row, first_base) for row in groups]
    before_base = sum(item[0] for item in coverage)
    parked_due = sum(item[1] for item in coverage)
    pending = total - before_base
    due = total_due - parked_due
    warning = bool(pending or preflight.get("warnings") or preflight.get("blockers")
                   or not receivables or any(
                       r.get("receivable_quality") not in {"NONE", "REPORTED_CALIBRATED", "ESTIMATED_NET"}
                       for r in receivables))
    return {"pending": pending, "due": due, "warning": warning,
            "groups": groups, "details": details, "receivables": receivables,
            "first_base_anchor": first_base, "before_base_anchor": before_base,
            "total_pending": total}


def render_followup(report: dict) -> str:
    lines = ["", "## NAV-historikk – kø for nytt forsøk", "",
             f"- Historikkpunkter i aktiv kø: **{report['pending']}**",
             f"- Bevarte køpunkter utenfor dokumentert kostnadsdekning: **{report['before_base_anchor']}**",
             f"- Forfalt til nytt forsøk: **{report['due']}**",
             "- Køen er ikke det samme som antall feil i dagens NAV.", "",
             "| Årsak | Antall | Første dato | Siste dato | Eldste registrerte feil | Maks forsøk | Forfalt |",
             "|---|---:|---|---|---|---:|---:|"]
    for row in report["groups"]:
        lines.append(f"| {_reason(row.get('reason_code'))} | {_fmt(row.get('count'))} | "
                     f"{_date(row.get('first_date'))} | {_date(row.get('last_date'))} | "
                     f"{_date(row.get('first_failed_at'))} | {_fmt(row.get('max_attempts'))} | {_fmt(row.get('due'))} |")
    lines += ["", f"- Tidligste gyldige BASE-kostnadsanker i D1: {report.get('first_base_anchor') or 'ikke bekreftet'}.",
              f"- Parkeringsgrunnlag: {report.get('before_base_anchor', 0)} datoer før første BASE-anker.",
              "- Disse punktene beholdes med opprinnelig feilhistorikk, men teller ikke som aktive forsøk. Et tidligere gyldig anker gjør dem aktuelle igjen. Øvrige årsaker må undersøkes separat."]
    if report["details"]:
        lines += ["", "### Datoer i historikkøen", "",
                  "| Datadato | Årsak | Forsøk | Første feil | Siste feil | Neste forsøk |",
                  "|---|---|---:|---|---|---|"]
        for row in report["details"]:
            lines.append(f"| {_date(row.get('date'))} | {_reason(row.get('reason_code'))} | "
                         f"{_fmt(row.get('attempts'))} | {_date(row.get('first_failed_date'))} | "
                         f"{_date(row.get('last_failed_date'))} | {_date(row.get('next_retry_date'))} |")
        if report["total_pending"] > len(report["details"]):
            lines.append(f"- Viser {len(report['details'])} av {report['total_pending']} bevarte køpunkter.")
    lines += ["", "## Bemobi-fordringer – siste FULL NAV", ""]
    if not report["receivables"]:
        lines.append("- Fordringsgrunnlag ikke bekreftet.")
    for row in report["receivables"]:
        quality = _choice(row.get("receivable_quality"), {"NONE", "ESTIMATED_GROSS", "REPORTED_CALIBRATED", "ESTIMATED_NET"})
        lines.append(f"- Datadato {_date(row.get('estimate_date'))}: {quality}; "
                     f"samlet modellert fordring {_fmt(row.get('associated_receivable_nok'))} NOK.")
        if quality == "ESTIMATED_NET":
            lines.append("  - Modellinformasjon: dokumentert standard nettoutdeling; Otellos faktiske skattebehandling er ikke bekreftet.")
        if row.get("modeled_action_id") is None:
            continue
        lines.append(f"  - Utdeling ID {_fmt(row.get('action_id'))}, "
                     f"{_choice(row.get('action_type'), {'JCP', 'DIVIDEND'})}, "
                     f"ex {_date(row.get('ex_date'))}, betaling {_date(row.get('payment_date'))}, "
                     f"kildedokument {_fmt(row.get('source_document_id'))}.")
        lines.append(f"  - Brutto per aksje {_fmt(row.get('gross_per_share'))} BRL; "
                     f"publisert netto {_fmt(row.get('net_amount_per_share'))} BRL; "
                     f"kildeskattesats (desimal) {_fmt(row.get('withholding_rate'))}; "
                     f"modellert beløp {_fmt(row.get('modeled_amount_nok'))} NOK.")
        gross, net, shares, fx = (_number(row.get(key)) for key in
                                 ("gross_per_share", "net_amount_per_share", "holding_shares", "brl_nok"))
        if (None not in (gross, net, shares, fx) and 0 < net <= gross
                and shares > 0 and shares == shares.to_integral_value() and fx > 0
                and row.get("source_document_id") is not None
                and row.get("tax_treatment") == "PUBLISHED_NET"):
            difference = (gross - net) * shares * fx
            lines.append(f"  - Illustrativ nettofordring ved publisert standard kildeskatt: "
                         f"{net * shares * fx:.2f} NOK; forskjell brutto/netto {difference:.2f} NOK. "
                         "Otello-spesifikk skatt er ikke bekreftet.")
    return "\n".join(lines) + "\n"

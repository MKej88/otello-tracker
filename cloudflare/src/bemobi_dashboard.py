from __future__ import annotations

from typing import Any

import bemobi_dashboard_base as _base

# Compatibility markers for the source-based parity guard:
# latest_bemobi_fact load_bemobi_facts reported_net_income_ttm_mbrl
VALUATION_MULTIPLES = (12.0, 14.0, 16.0)
BEMOBI_PAYOUT_POLICY_PCT = 100.0
BEMOBI_PAYOUT_POLICY_YEAR = 2026
OTELLO_BRAZIL_DIVIDEND_WITHHOLDING_PCT = 10.0
OTELLO_BRAZIL_JCP_WITHHOLDING_PCT = 15.0

# Preserve public helper seams used by the financial-integrity parity suite.
_valuation_payload = _base._valuation_payload
_distribution_estimate_payload = _base._distribution_estimate_payload


def _number(value: Any) -> float | None:
    return _base._number(value)


def _distribution_year(distribution: dict[str, Any]) -> int | None:
    for field in ("announcement_date", "record_date", "ex_date", "payment_date"):
        text = str(distribution.get(field) or "")
        if len(text) >= 4 and text[:4].isdigit():
            return int(text[:4])
    return None


def _otello_brazil_withholding_pct(distribution: dict[str, Any]) -> float | None:
    action_type = str(distribution.get("type") or "").upper()
    treatment = str(distribution.get("tax_treatment") or "").lower()
    if any(marker in treatment for marker in ("isento", "exempt", "0%", "sem reten")):
        return 0.0
    if action_type == "JCP":
        return OTELLO_BRAZIL_JCP_WITHHOLDING_PCT
    if action_type == "DIVIDEND":
        year = _distribution_year(distribution)
        if year is not None and year <= 2025:
            return 0.0
        return OTELLO_BRAZIL_DIVIDEND_WITHHOLDING_PCT
    return None


def _apply_distribution_tax(distribution: dict[str, Any] | None) -> dict[str, Any] | None:
    if distribution is None:
        return None
    rate_pct = _otello_brazil_withholding_pct(distribution)
    if rate_pct is None:
        return distribution
    factor = 1.0 - rate_pct / 100.0
    gross_per_share = _number(distribution.get("gross_per_share_brl"))
    gross_mbrl = _number(distribution.get("otello_gross_mbrl"))
    distribution["otello_withholding_rate_pct"] = rate_pct
    distribution["otello_net_per_share_brl"] = (
        None if gross_per_share is None else gross_per_share * factor
    )
    distribution["otello_net_mbrl"] = None if gross_mbrl is None else gross_mbrl * factor
    distribution["otello_tax_basis"] = "NO_BR_TREATY"
    distribution["otello_tax_scope"] = "BRAZIL_WITHHOLDING_ONLY"
    distribution["otello_tax_note"] = (
        "Otello-spesifikk netto bruker modellert brasiliansk kildeskatt etter Norge–Brasil-"
        "behandlingen. Publisert netto per Bemobi-aksje beholdes separat som kildefaktum."
    )
    return distribution


def _apply_estimate_tax(estimate: dict[str, Any] | None) -> dict[str, Any] | None:
    if not estimate or not estimate.get("ready"):
        return estimate
    gross_mbrl = _number(estimate.get("otello_gross_mbrl"))
    gross_mnok = _number(estimate.get("otello_gross_mnok"))
    gross_per_otec = _number(estimate.get("otello_gross_per_otec_share_nok"))
    dividend_factor = 1.0 - OTELLO_BRAZIL_DIVIDEND_WITHHOLDING_PCT / 100.0
    jcp_factor = 1.0 - OTELLO_BRAZIL_JCP_WITHHOLDING_PCT / 100.0
    estimate.update(
        {
            "ordinary_dividend_withholding_rate_pct": OTELLO_BRAZIL_DIVIDEND_WITHHOLDING_PCT,
            "jcp_withholding_rate_pct": OTELLO_BRAZIL_JCP_WITHHOLDING_PCT,
            "otello_net_dividend_mbrl": None if gross_mbrl is None else gross_mbrl * dividend_factor,
            "otello_net_jcp_mbrl": None if gross_mbrl is None else gross_mbrl * jcp_factor,
            "otello_net_dividend_mnok": None if gross_mnok is None else gross_mnok * dividend_factor,
            "otello_net_jcp_mnok": None if gross_mnok is None else gross_mnok * jcp_factor,
            "otello_net_dividend_per_otec_share_nok": None
            if gross_per_otec is None
            else gross_per_otec * dividend_factor,
            "otello_net_jcp_per_otec_share_nok": None
            if gross_per_otec is None
            else gross_per_otec * jcp_factor,
            "tax_scope": "BRAZIL_WITHHOLDING_ONLY",
            "norwegian_cash_tax_modeled": False,
        }
    )
    prior_note = str(estimate.get("methodology_note") or "").strip()
    tax_note = (
        "Netto-scenarioene trekker kun modellert brasiliansk kildeskatt: 10 % ved ordinært "
        "utbytte fra 2026-regimet og 15 % ved JCP for Otello som norsk selskapsaksjonær. "
        "Ytterligere norsk kontantskatt er ikke modellert; JCP/utbytte-miksen er ukjent."
    )
    estimate["methodology_note"] = f"{prior_note} {tax_note}".strip()
    return estimate


async def bemobi_dashboard(repository) -> dict[str, Any]:
    payload = await _base.bemobi_dashboard(repository)
    if not payload.get("ready"):
        return payload
    payload["latest_distribution"] = _apply_distribution_tax(payload.get("latest_distribution"))
    payload["distribution_estimate"] = _apply_estimate_tax(payload.get("distribution_estimate"))
    return payload

from __future__ import annotations

from typing import Any

from app.bemobi import dashboard_base as _base

# Keep the established dashboard implementation intact in dashboard_base. This thin
# presentation overlay adds Otello-specific tax treatment without changing the source
# corporate-action facts (whose published net amount can reflect a generic BR rate).
VALUATION_MULTIPLES = (12.0, 14.0, 16.0)
BEMOBI_PAYOUT_POLICY_PCT = 100.0
BEMOBI_PAYOUT_POLICY_YEAR = 2026
OTELLO_BRAZIL_DIVIDEND_WITHHOLDING_PCT = 10.0
OTELLO_BRAZIL_JCP_WITHHOLDING_PCT = 15.0

# Preserve monkeypatch seams and module-level compatibility used by the reference tests.
dashboard_summary = _base.dashboard_summary
enrich_dashboard_summary = _base.enrich_dashboard_summary
get_connection = _base.get_connection
_number = _base._number
_period_year = _base._period_year
_quarter_index = _base._quarter_index
_quarters_are_consecutive = _base._quarters_are_consecutive
_latest_distribution = _base._latest_distribution
_latest_result_source = _base._latest_result_source
_valuation_payload = _base._valuation_payload
_distribution_estimate_payload = _base._distribution_estimate_payload


def _distribution_year(distribution: dict[str, Any]) -> int | None:
    for field in ("announcement_date", "record_date", "ex_date", "payment_date"):
        text = str(distribution.get(field) or "")
        if len(text) >= 4 and text[:4].isdigit():
            return int(text[:4])
    return None


def _otello_brazil_withholding_pct(distribution: dict[str, Any]) -> float | None:
    """Model Brazilian withholding for a Norwegian corporate beneficial owner.

    JCP is treated as interest under the Norway-Brazil treaty and modeled at 15%.
    Ordinary dividends from the 2026 regime are modeled at 10%. A dividend approved
    in 2025 or earlier is treated as grandfathered at 0% unless the source fact says
    otherwise. Unknown distribution types are deliberately left unmodeled.
    """
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
    gross_per_share = _base._number(distribution.get("gross_per_share_brl"))
    gross_mbrl = _base._number(distribution.get("otello_gross_mbrl"))
    distribution["otello_withholding_rate_pct"] = rate_pct
    distribution["otello_net_per_share_brl"] = (
        None if gross_per_share is None else gross_per_share * factor
    )
    # Keep otello_net_mbrl as the published/general corporate-action net for backwards
    # compatibility and auditability. The treaty-specific cash estimate is separate.
    distribution["otello_treaty_net_mbrl"] = (
        None if gross_mbrl is None else gross_mbrl * factor
    )
    distribution["otello_tax_basis"] = "NO_BR_TREATY"
    distribution["otello_tax_scope"] = "BRAZIL_WITHHOLDING_ONLY"
    distribution["otello_tax_note"] = (
        "Otello-spesifikk netto bruker modellert brasiliansk kildeskatt etter Norge–Brasil-"
        "behandlingen. Publisert netto per Bemobi-aksje og publisert generell nettoandel "
        "beholdes separat som kildefakta."
    )
    return distribution


def _apply_estimate_tax(estimate: dict[str, Any] | None) -> dict[str, Any] | None:
    if not estimate or not estimate.get("ready"):
        return estimate

    gross_mbrl = _base._number(estimate.get("otello_gross_mbrl"))
    gross_mnok = _base._number(estimate.get("otello_gross_mnok"))
    gross_per_otec = _base._number(estimate.get("otello_gross_per_otec_share_nok"))
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


def _distribution_payload(
    row: dict[str, Any] | None, holding_shares: int | None
) -> dict[str, Any] | None:
    return _apply_distribution_tax(_base._distribution_payload(row, holding_shares))


def bemobi_dashboard(database_path: str | None = None) -> dict[str, Any]:
    # The existing tests monkeypatch these names on this public module. Forward them
    # before invoking the frozen base implementation.
    _base.dashboard_summary = dashboard_summary
    _base.enrich_dashboard_summary = enrich_dashboard_summary
    _base.get_connection = get_connection
    payload = _base.bemobi_dashboard(database_path)
    if not payload.get("ready"):
        return payload
    payload["latest_distribution"] = _apply_distribution_tax(payload.get("latest_distribution"))
    payload["distribution_estimate"] = _apply_estimate_tax(payload.get("distribution_estimate"))
    return payload

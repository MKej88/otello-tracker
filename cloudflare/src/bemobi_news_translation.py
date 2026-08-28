from __future__ import annotations

from typing import Any

_CVM_TERMS = {
    "assembleia": "Shareholders' meeting",
    "ata": "Minutes",
    "aviso aos acionistas": "Notice to shareholders",
    "calendário de eventos corporativos": "Corporate events calendar",
    "comunicado ao mercado": "Notice to the market",
    "dados econômico-financeiros": "Financial information",
    "demonstrações financeiras anuais completas": "Annual financial statements",
    "demonstrações financeiras intermediárias": "Interim financial statements",
    "fato relevante": "Material fact",
    "reunião da administração": "Board meeting",
    "relatório proventos": "Distribution report",
}

_SUBJECT_TERMS = {
    "apresentação de resultados": "Earnings presentation",
    "aumento de capital": "Capital increase",
    "cancelamento de ações": "Cancellation of shares",
    "dividendos": "Dividends",
    "juros sobre capital próprio": "Interest on equity",
    "programa de recompra de ações": "Share buyback program",
    "redução de capital": "Capital reduction",
}


def _translate_term(value: Any, terms: dict[str, str]) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    direct = terms.get(text.casefold())
    if direct:
        return direct
    lowered = text.casefold()
    for portuguese, english in terms.items():
        if portuguese in lowered:
            return english
    return None


def translate_bemobi_news(
    *,
    headline: Any,
    summary: Any,
    metadata: dict[str, Any],
) -> tuple[str, str | None]:
    """Return an English, metadata-based rendering of a Bemobi CVM filing."""
    category = _translate_term(metadata.get("cvm_category"), _CVM_TERMS)
    document_type = _translate_term(metadata.get("cvm_type"), _CVM_TERMS)
    species = _translate_term(metadata.get("cvm_species"), _CVM_TERMS)
    subject = _translate_term(metadata.get("cvm_subject"), _SUBJECT_TERMS)

    filing_type = category or document_type or species
    detail = subject or document_type or species
    if filing_type:
        translated_headline = (
            f"{filing_type} — {detail}"
            if detail and detail != filing_type
            else filing_type
        )
        summary_parts = [f"Filing type: {filing_type}"]
        if subject:
            summary_parts.append(f"Subject: {subject}")
        summary_parts.append("See the official CVM filing for full details.")
        return translated_headline, " | ".join(summary_parts)

    return str(headline or "Bemobi announcement"), str(summary) if summary else None

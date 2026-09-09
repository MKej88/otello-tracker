from __future__ import annotations

from typing import Any

_CVM_TERMS = {
    "assembleia": "Generalforsamling",
    "ata": "Protokoll",
    "aviso aos acionistas": "Melding til aksjonærene",
    "calendário de eventos corporativos": "Finansiell kalender",
    "comunicado ao mercado": "Markedsmelding",
    "dados econômico-financeiros": "Finansiell informasjon",
    "demonstrações financeiras anuais completas": "Årsregnskap",
    "demonstrações financeiras intermediárias": "Delårsregnskap",
    "fato relevante": "Vesentlig melding",
    "reunião da administração": "Styremøte",
    "relatório proventos": "Distribusjonsrapport",
}

_SUBJECT_TERMS = {
    "apresentação de resultados": "Resultatpresentasjon",
    "aumento de capital": "Kapitalforhøyelse",
    "cancelamento de ações": "Sletting av aksjer",
    "dividendos": "Utbytte",
    "juros sobre capital próprio": "Renter på egenkapital (JCP)",
    "programa de recompra de ações": "Tilbakekjøpsprogram for aksjer",
    "redução de capital": "Kapitalnedsettelse",
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
    """Returner norsk metadata-fallback når dokumentanalyse ikke er klar."""
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
        summary_parts = [f"Dokumenttype: {filing_type}"]
        if subject:
            summary_parts.append(f"Emne: {subject}")
        summary_parts.append(
            "Se det offisielle CVM-dokumentet for fullstendige detaljer."
        )
        return translated_headline, " | ".join(summary_parts)

    return str(headline or "Bemobi-melding"), str(summary) if summary else None

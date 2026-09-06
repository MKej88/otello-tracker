from __future__ import annotations

import re
import unicodedata
from typing import Any

_RELEVANCE_PATTERNS = (
    re.compile(r"\bbemobi\b", re.IGNORECASE),
    re.compile(r"\bbmob3\b", re.IGNORECASE),
    re.compile(r"\bpedro\s+ripper\b", re.IGNORECASE),
)

_NON_NEWS_PATTERNS = (
    "real time graph",
    "real time chart",
    "grafico em tempo real",
    "cotacao em tempo real",
    "stock price",
    "share price",
    "historical data",
    "dados historicos",
    "technical analysis",
    "analise tecnica",
    "company profile",
    "perfil da empresa",
    "investment recommendation",
    "recomendacao de investimento",
)

_PAYWALL_PUBLISHERS = (
    "o globo",
    "valor economico",
    "estadao",
    "o estado de s paulo",
    "folha de s paulo",
    "bloomberg",
)

_MATERIAL_TERMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "RESULTS",
        (
            "resultado",
            "resultados",
            "balanco",
            "lucro",
            "profit",
            "earnings",
            "ebitda",
            "receita",
            "revenue",
        ),
    ),
    (
        "M_AND_A",
        (
            "aquisicao",
            "adquire",
            "fusao",
            "m&a",
            "acquisition",
            "merger",
        ),
    ),
    ("BUYBACK", ("recompra", "buyback")),
    ("JCP", ("juros sobre capital", "jcp")),
    ("DIVIDEND", ("dividendo", "dividend")),
    (
        "GUIDANCE",
        (
            "guidance",
            "projecao",
            "projecoes",
            "perspectiva",
            "perspectivas",
            "outlook",
        ),
    ),
    (
        "CORPORATE",
        (
            "parceria",
            "partnership",
            "contrato",
            "contract",
            "cliente",
            "customer",
            "acordo",
            "agreement",
            "operadora",
            "operator",
            "lancamento",
            "launch",
        ),
    ),
)


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _fold(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", _clean(value).casefold())
    without_marks = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9&]+", " ", without_marks).strip()


def media_is_relevant(title: Any, summary: Any = None) -> bool:
    """Return True only when RSS metadata explicitly supports Bemobi relevance.

    Search-engine queries are treated as discovery only. A result must still mention
    Bemobi, BMOB3 or Pedro Ripper in its own title/summary metadata and must not look
    like a quote page, chart, company profile, disclaimer or technical-analysis page.
    """
    title_text = _clean(title)
    summary_text = _clean(summary)
    haystack = f"{title_text} {summary_text}"
    if not any(pattern.search(haystack) for pattern in _RELEVANCE_PATTERNS):
        return False

    folded = _fold(haystack)
    return not any(pattern in folded for pattern in _NON_NEWS_PATTERNS)


def classify_media_item(title: Any, summary: Any = None) -> tuple[str, str]:
    """Classify investor relevance without promoting ordinary media by default."""
    folded = _fold(f"{_clean(title)} {_clean(summary)}")
    for category, terms in _MATERIAL_TERMS:
        if any(term in folded for term in terms):
            return category, "POTENTIAL"
    return "OTHER", "NONE"


def media_paywall_likely(publisher: Any) -> bool:
    folded = _fold(publisher)
    return any(name in folded for name in _PAYWALL_PUBLISHERS)


def media_story_key(title: Any, published_at: Any = None) -> str:
    """Create a conservative deduplication key for the same headline on the same day."""
    folded = _fold(title)
    date_part = _clean(published_at)[:10]
    return f"{folded}|{date_part}"


def media_should_be_shown(
    *,
    title: Any,
    summary: Any = None,
    publisher: Any = None,
) -> bool:
    """Investor-facing visibility rule used for both new and previously stored media."""
    if not media_is_relevant(title, summary):
        return False
    category, _ = classify_media_item(title, summary)
    if media_paywall_likely(publisher) and category == "OTHER":
        return False
    return True

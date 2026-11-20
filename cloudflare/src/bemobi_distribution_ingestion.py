"""Validated, source-linked Bemobi distributions from official shareholder notices.

The IR feed is discovery only. No NAV-impacting action is recorded unless the
issuer's PDF contains a complete, internally consistent single distribution.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

from bemobi_ir_news import COMPANY_ID, STATE_KEY
from bemobi_web_refresh import _fetch_result_payload, _pdf_text

_MONTHS = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4,
    "maio": 5, "junho": 6, "julho": 7, "agosto": 8,
    "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
}
_DATE = (
    r"(?P<day>\d{1,2})\s+de\s+"
    r"(?P<month>janeiro|fevereiro|marco|abril|maio|junho|julho|agosto|"
    r"setembro|outubro|novembro|dezembro)\s+de\s+(?P<year>20\d{2})"
)
_BRL = r"(\d[\d.]*,\d{1,11})"
_LOOKBACK_DAYS = 180
_MAX_NOTICES = 12


def _normalise(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    normalized = re.sub(r"\s+", " ", ascii_text).lower().strip()
    # pypdf can split digits inside official amounts (e.g. "13. 2 00.000,00",
    # "0, 158 22091", or "0.15822 091"). Join only currency amount digits,
    # never unrelated dates, share counts, or sentences.
    normalized = re.sub(
        r"r\$\s*(\d[\d.,\s]*\d)",
        lambda match: "r$ " + re.sub(r"\s+", "", match.group(1)),
        normalized,
    )
    # A broken withholding percentage can be extracted as "1 7, 5%".
    normalized = re.sub(r"(?<=\d)\s+(?=\d\s*[,%.])", "", normalized)
    return re.sub(r"(?<=\d)([.,])\s+(?=\d)", r"\1", normalized)


def _money(text: str, pattern: str, label: str) -> Decimal:
    found = re.search(pattern, text)
    if found is None:
        raise ValueError(f"missing_{label}")
    try:
        value = Decimal(found.group(1).replace(".", "").replace(",", "."))
    except InvalidOperation as exc:
        raise ValueError(f"invalid_{label}") from exc
    if value <= 0:
        raise ValueError(f"invalid_{label}")
    return value


def _date_after(text: str, pattern: str, label: str) -> str:
    found = re.search(pattern + _DATE, text)
    if found is None:
        raise ValueError(f"missing_{label}")
    try:
        return date(
            int(found.group("year")),
            _MONTHS[found.group("month")],
            int(found.group("day")),
        ).isoformat()
    except ValueError as exc:
        raise ValueError(f"invalid_{label}") from exc


_EN_BRL = r"(\d[\d,]*\.\d{1,11})"
_EN_DATE = (
    r"(?P<month>january|february|march|april|may|june|july|august|"
    r"september|october|november|december)\s+"
    r"(?P<day>\d{1,2})\s*,?\s*(?P<year>20\d{2})"
)
_EN_MONTHS = {
    name: index for index, name in enumerate(
        ("january", "february", "march", "april", "may", "june",
         "july", "august", "september", "october", "november", "december"),
        start=1,
    )
}


def _money_en(text: str, pattern: str, label: str) -> Decimal:
    match = re.search(pattern, text)
    if match is None:
        raise ValueError(f"missing_{label}")
    value = Decimal(match.group(1).replace(",", ""))
    if value <= 0:
        raise ValueError(f"invalid_{label}")
    return value


def _date_after_en(text: str, pattern: str, label: str) -> str:
    match = re.search(pattern + _EN_DATE, text)
    if match is None:
        raise ValueError(f"missing_{label}")
    try:
        return date(
            int(match.group("year")),
            _EN_MONTHS[match.group("month")],
            int(match.group("day")),
        ).isoformat()
    except ValueError as exc:
        raise ValueError(f"invalid_{label}") from exc


def _nearly_equal(first: Decimal, second: Decimal, tolerance: Decimal) -> bool:
    return abs(first - second) <= tolerance


def parse_official_distribution(text: str, *, published_date: str) -> dict[str, str]:
    """Strictly parse one verified Portuguese or English Bemobi JCP notice.

    Accept alternative issuer languages, not missing dates/amounts or inferred
    values. Every financial amount, entitlement date and tax rate must appear
    in the original PDF and must reconcile arithmetically.
    """
    body = _normalise(text)
    heading = body[:800]
    if "bemobi mobile tech" not in heading or "bmob3" not in heading:
        raise ValueError("issuer_not_verified")

    english = "notice to shareholders" in heading
    if english:
        if "interest on equity" not in heading:
            raise ValueError("not_distribution")
        if re.search(r"dividends\s+and\s+(?:interest on equity|ioe)", heading):
            raise ValueError("mixed_distribution_requires_review")
        action_type = "JCP"
        gross_total = _money_en(
            body, r"total distribution amount will be r\$\s*" + _EN_BRL,
            "gross_total",
        )
        gross_share = _money_en(
            body, r"gross value of r\$\s*" + _EN_BRL + r"\s+per share",
            "gross_per_share",
        )
        record_date = _date_after_en(
            body, r"shareholders at the close of the trading session on\s+",
            "record_date",
        )
        ex_date = _date_after_en(
            body, r"traded\s+ex\s*-\s*interest on equity\s+as from\s+",
            "ex_date",
        )
        payment_date = _date_after_en(
            body, r"payment of interest on equity to shareholders will take place on\s+",
            "payment_date",
        )
    else:
        if "aviso aos acionistas" not in heading:
            raise ValueError("not_shareholder_notice")
        if "juros sobre capital proprio" in heading:
            action_type = "JCP"
            if re.search(r"(?:dividendos e jcp|dividendos e juros sobre capital)", heading):
                raise ValueError("mixed_distribution_requires_review")
        elif "dividendos" in heading:
            action_type = "DIVIDEND"
        else:
            raise ValueError("not_distribution")
        gross_total = _money(
            body, r"valor total da distribuicao (?:sera|e) de r\$\s*" + _BRL,
            "gross_total",
        )
        gross_share = _money(
            body, r"valor bruto de r\$\s*" + _BRL + r"\s+por acao",
            "gross_per_share",
        )
        record_date = _date_after(
            body, r"(?:fechamento|encerramento) do pregao (?:de|do dia)\s+",
            "record_date",
        )
        ex_date = _date_after(
            body,
            r"ex\s*-\s*(?:juros sobre (?:o )?capital proprio|jcp|dividendos?)"
            r".{0,110}?\ba partir de\s+",
            "ex_date",
        )
        payment_date = _date_after(
            body,
            r"\bpagamento\b.{0,130}?\b(?:ocorrera|sera realizado|sera efetuado)"
            r"\s+em\s+",
            "payment_date",
        )

    if gross_share > 100 or gross_total > 10_000_000_000:
        raise ValueError("implausible_distribution")
    announcement = date.fromisoformat(published_date)
    record = date.fromisoformat(record_date)
    ex = date.fromisoformat(ex_date)
    paid = date.fromisoformat(payment_date)
    if not (announcement <= record < ex <= paid <= announcement + timedelta(days=366)):
        raise ValueError("inconsistent_distribution_dates")

    result = {
        "action_type": action_type,
        "announcement_date": announcement.isoformat(),
        "record_date": record_date,
        "ex_date": ex_date,
        "payment_date": payment_date,
        "gross_amount_per_share": str(gross_share),
        "gross_total_amount": str(gross_total),
        "net_amount_per_share": None,
        "net_total_amount": None,
        "withholding_rate": None,
        "tax_treatment": "UNSPECIFIED",
    }
    if action_type == "JCP":
        if english:
            net_total = _money_en(
                body, r"net value of r\$\s*" + _EN_BRL,
                "net_total",
            )
            net_match = re.search(
                r"net value of r\$\s*" + _EN_BRL
                + r".{0,230}?corresponding to r\$\s*"
                + _EN_BRL + r"\s+per share",
                body,
            )
            if net_match is None:
                raise ValueError("missing_net_per_share")
            net_share = Decimal(net_match.group(2).replace(",", ""))
            rate = _money_en(
                body,
                r"withholding income tax at the rate of\s*"
                r"(\d+(?:\.\d+)?)\s*%",
                "withholding",
            ) / 100
        else:
            net_total = _money(
                body, r"valor liquido de r\$\s*" + _BRL, "net_total",
            )
            net_match = re.search(
                r"valor liquido de r\$\s*" + _BRL
                + r".{0,230}?\bcorrespondente a r\$\s*"
                + _BRL + r"\s+por acao",
                body,
            )
            if net_match is None:
                raise ValueError("missing_net_per_share")
            net_share = Decimal(net_match.group(2).replace(".", "").replace(",", "."))
            rate = _money(
                body, r"\baliquota de\s*" + _BRL + r"\s*%", "withholding",
            ) / 100
        if not (Decimal("0") < rate < Decimal("1")):
            raise ValueError("invalid_withholding")
        if not _nearly_equal(net_total, gross_total * (1 - rate), Decimal("1.00")):
            raise ValueError("net_total_mismatch")
        if not _nearly_equal(
            net_share, gross_share * (1 - rate), Decimal("0.0000001")
        ):
            raise ValueError("net_per_share_mismatch")
        if not _nearly_equal(
            gross_total / gross_share, net_total / net_share,
            gross_total / gross_share * Decimal("0.002"),
        ):
            raise ValueError("inconsistent_share_count")
        result.update({
            "net_amount_per_share": str(net_share),
            "net_total_amount": str(net_total),
            "withholding_rate": str(rate),
            "tax_treatment": "PUBLISHED_NET",
        })
    elif "sem retencao" not in body:
        raise ValueError("dividend_tax_treatment_unverified")
    else:
        result["net_amount_per_share"] = str(gross_share)
        result["net_total_amount"] = str(gross_total)
        result["tax_treatment"] = "PUBLISHED_NET"
    return result

def _valid_notice(row: dict, *, target_date: str) -> bool:
    if row.get("document_kind") != "NOTICE":
        return False
    if row.get("category") not in (
        "comunicados", "aviso-acionistas", "fatos-relevantes-e-comunicados"
    ):
        return False
    url = str(row.get("url") or "")
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"api.mziq.com", "filemanager-cdn.mziq.com"}
        or f"/{COMPANY_ID}/" not in parsed.path
        or not str(row.get("id") or "").strip()
    ):
        return False
    try:
        published = date.fromisoformat(str(row["date"]))
        target = date.fromisoformat(target_date)
    except (KeyError, ValueError, TypeError):
        return False
    return target - timedelta(days=_LOOKBACK_DAYS) <= published <= target


async def refresh_official_distributions(
    repository, *, target_date: str, fetcher=None
) -> dict:
    """Upsert new, verified corporate actions before NAV and cash refresh."""
    state = await repository.first(
        "SELECT value FROM runtime_state WHERE key=? LIMIT 1", (STATE_KEY,)
    )
    if state is None:
        return {"status": "not_available", "reason": "official_notice_feed_missing",
                "rows_written": 0, "review_required": 0}
    try:
        snapshot = json.loads(str(state["value"]))
        if date.fromisoformat(str(snapshot["checked_date"])) > date.fromisoformat(target_date):
            raise ValueError("future_feed_snapshot")
        notices = snapshot["rows"]
        if not isinstance(notices, list):
            raise ValueError("invalid_feed_rows")
    except (ValueError, KeyError, TypeError) as exc:
        return {"status": "not_available", "reason": str(exc),
                "rows_written": 0, "review_required": 0}

    relevant = []
    for row in notices:
        if not isinstance(row, dict) or not _valid_notice(row, target_date=target_date):
            continue
        title = _normalise(str(row.get("title") or "") + " "
                           + str(row.get("original_title") or ""))
        if any(term in title for term in (
            "dividend", "juros sobre capital", "juros sobre o capital",
            "jcp", "aviso aos acionistas", "notice to shareholders",
        )):
            relevant.append(row)
    relevant.sort(key=lambda item: (item["date"], str(item["id"])), reverse=True)
    review: list[dict[str, str]] = []
    created = 0
    unchanged = 0
    ignored = 0

    for row in relevant[:_MAX_NOTICES]:
        external_id = f"bemobi-ir-distribution:{row['id']}"
        try:
            original_url = str(row["url"])
            payload, resolved_url, _ = await _fetch_result_payload(
                original_url, fetcher=fetcher,
            )
            resolved = urlsplit(resolved_url)
            if (
                resolved.hostname not in {"api.mziq.com", "filemanager-cdn.mziq.com"}
                or f"/{COMPANY_ID}/" not in resolved.path
                or not payload.startswith(b"%PDF")
            ):
                raise ValueError("unverified_issuer_pdf")
            parsed = parse_official_distribution(
                _pdf_text(payload), published_date=str(row["date"]),
            )
            existing = await repository.first(
                """
                SELECT ca.id, ca.action_type, ca.ex_date, ca.payment_date,
                       ca.amount_per_share
                FROM corporate_actions ca
                JOIN instruments i ON i.id=ca.issuer_instrument_id
                WHERE i.symbol='BMOB3'
                  AND (ca.external_action_id=?
                       OR (ca.action_type=? AND ca.ex_date=? AND ca.payment_date=?))
                LIMIT 1
                """,
                (external_id, parsed["action_type"], parsed["ex_date"],
                 parsed["payment_date"]),
            )
            if existing is not None:
                if (
                    existing["action_type"] != parsed["action_type"]
                    or existing["ex_date"] != parsed["ex_date"]
                    or existing["payment_date"] != parsed["payment_date"]
                    or not _nearly_equal(
                        Decimal(str(existing["amount_per_share"])),
                        Decimal(parsed["gross_amount_per_share"]),
                        Decimal("0.00000001"),
                    )
                ):
                    raise ValueError("conflicting_existing_distribution")
                unchanged += 1
                continue

            doc_id = await repository.create_source_document(
                source_code="BEMOBI_IR",
                external_id=f"bemobi-ir-distribution-document:{row['id']}",
                document_type="SHAREHOLDER_DISTRIBUTION_NOTICE",
                title=str(row["title"]),
                url=resolved_url,
                published_at=f"{row['date']}T00:00:00Z",
                content_sha256=hashlib.sha256(payload).hexdigest(),
                metadata={
                    "mziq_document_id": str(row["id"]),
                    "original_url": original_url,
                    "validation": "OFFICIAL_NOTICE_STRICT",
                },
            )
            issuer_id = await repository.instrument_id("BMOB3")
            await repository.run(
                """
                INSERT INTO corporate_actions(
                    issuer_instrument_id, action_type, announcement_date,
                    ex_date, record_date, payment_date, amount_per_share,
                    total_amount, currency, source_document_id, notes,
                    external_action_id, gross_amount_per_share,
                    net_amount_per_share, gross_total_amount, net_total_amount,
                    withholding_rate, tax_treatment
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'BRL', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT DO NOTHING
                """,
                (issuer_id, parsed["action_type"],
                 parsed["announcement_date"], parsed["ex_date"],
                 parsed["record_date"], parsed["payment_date"],
                 parsed["gross_amount_per_share"],
                 parsed["gross_total_amount"], doc_id,
                 "Verified official Bemobi shareholder notice; "
                 "gross receivable until payment; payment-date net cash for JCP.",
                 external_id, parsed["gross_amount_per_share"],
                 parsed["net_amount_per_share"], parsed["gross_total_amount"],
                 parsed["net_total_amount"], parsed["withholding_rate"],
                 parsed["tax_treatment"]),
            )
            created += 1
        except ValueError as exc:
            if str(exc) in {"not_shareholder_notice", "not_distribution"}:
                ignored += 1
                continue
            review.append({"id": str(row["id"]), "date": str(row["date"]),
                           "reason": str(exc)[:180]})
        except Exception as exc:
            review.append({"id": str(row["id"]), "date": str(row["date"]),
                           "reason": f"{type(exc).__name__}: {str(exc)[:150]}"})

    return {
        "status": "partial" if review or len(relevant) > _MAX_NOTICES else "ok",
        "rows_written": created,
        "unchanged": unchanged,
        "ignored": ignored,
        "notices_checked": min(len(relevant), _MAX_NOTICES),
        "review_required": len(review) + max(0, len(relevant) - _MAX_NOTICES),
        "review": review[:6],
        "source": "Bemobi official MZiQ shareholder notices",
    }

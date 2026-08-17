from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

_DATE_RE = re.compile(r"\d{2}\.\d{2}\.\d{4}")
_TIME_RE = re.compile(r"\d{2}:\d{2}:\d{2}")
_EXEC_BUY_RE = re.compile(r"^ExecBuy\s+([\d \u00a0]+)$", re.I)
_SELL_RE = re.compile(r"^S\s+OTEC\b", re.I)


@dataclass(frozen=True)
class BuybackTrade:
    trade_date: str
    trade_time: str
    shares: int
    price_nok: Decimal
    amount_nok: Decimal


@dataclass(frozen=True)
class DailyBuybackTransaction:
    trade_date: str
    shares: int
    avg_price_nok: Decimal
    amount_nok: Decimal
    trade_count: int


def _integer(value: str) -> int:
    return int(value.replace(" ", "").replace("\u00a0", ""))


def _decimal(value: str) -> Decimal:
    return Decimal(value.replace(" ", "").replace("\u00a0", "").replace(",", "."))


def _date(value: str) -> str:
    day, month, year = value.split(".")
    return date(int(year), int(month), int(day)).isoformat()


def _parse_trade_line(line: str) -> BuybackTrade | None:
    normalized = " ".join(line.replace("\u00a0", " ").split())
    if not normalized:
        return None
    if _SELL_RE.match(normalized):
        raise ValueError("NewsWeb buyback-vedlegg inneholder OTEC-salg; krever kontroll")
    if not normalized.upper().startswith("B OTEC "):
        return None

    date_match = _DATE_RE.search(normalized)
    time_match = _TIME_RE.search(normalized)
    if date_match is None or time_match is None:
        return None

    payload = normalized
    for match in sorted((date_match, time_match), key=lambda item: item.start(), reverse=True):
        payload = payload[: match.start()] + " " + payload[match.end() :]
    tokens = " ".join(payload.split())[len("B OTEC ") :].split()
    if len(tokens) < 3:
        return None

    candidates: list[tuple[int, Decimal, Decimal]] = []
    for price_index in range(1, len(tokens) - 1):
        try:
            shares = _integer("".join(tokens[:price_index]))
            price = _decimal(tokens[price_index])
            amount = _decimal("".join(tokens[price_index + 1 :]))
        except (ValueError, ArithmeticError):
            continue
        if shares <= 0 or price <= 0 or amount <= 0 or price > Decimal("500"):
            continue
        if abs(Decimal(shares) * price - amount) <= Decimal("0.01"):
            candidates.append((shares, price, amount))

    if not candidates:
        raise ValueError(f"Kunne ikke avstemme NewsWeb-handelslinje: {normalized}")
    # Decimal punctuation makes the price-token boundary explicit and is preferred when
    # more than one arithmetic partition can technically balance. Otherwise require one
    # unique economic tuple; ambiguity must never be silently guessed.
    punctuated = []
    for price_index in range(1, len(tokens) - 1):
        if "," not in tokens[price_index] and "." not in tokens[price_index]:
            continue
        try:
            candidate = (
                _integer("".join(tokens[:price_index])),
                _decimal(tokens[price_index]),
                _decimal("".join(tokens[price_index + 1 :])),
            )
        except (ValueError, ArithmeticError):
            continue
        if candidate in candidates:
            punctuated.append(candidate)
    selected_pool = punctuated or list(dict.fromkeys(candidates))
    if len(selected_pool) != 1:
        raise ValueError(f"Tvetydig NewsWeb-handelslinje; krever kontroll: {normalized}")
    shares, price, amount = selected_pool[0]
    return BuybackTrade(
        trade_date=_date(date_match.group(0)),
        trade_time=time_match.group(0),
        shares=shares,
        price_nok=price,
        amount_nok=amount,
    )


def parse_buyback_trade_lines(text: str) -> list[BuybackTrade]:
    trades = [parsed for line in text.splitlines() if (parsed := _parse_trade_line(line)) is not None]
    if not trades:
        raise ValueError("Fant ingen OTEC-kjøp i NewsWeb-transaksjonsvedlegget")
    return trades


def aggregate_daily_buybacks(trades: list[BuybackTrade]) -> list[DailyBuybackTransaction]:
    grouped: dict[str, list[BuybackTrade]] = defaultdict(list)
    for trade in trades:
        grouped[trade.trade_date].append(trade)
    result: list[DailyBuybackTransaction] = []
    for trade_date in sorted(grouped):
        rows = grouped[trade_date]
        shares = sum(row.shares for row in rows)
        amount = sum((row.amount_nok for row in rows), Decimal("0"))
        result.append(
            DailyBuybackTransaction(
                trade_date=trade_date,
                shares=shares,
                avg_price_nok=amount / Decimal(shares),
                amount_nok=amount,
                trade_count=len(rows),
            )
        )
    return result


def parse_buyback_transaction_text(text: str) -> list[DailyBuybackTransaction]:
    daily = aggregate_daily_buybacks(parse_buyback_trade_lines(text))
    exec_buys = [
        _integer(match.group(1))
        for raw in text.splitlines()
        if (match := _EXEC_BUY_RE.match(" ".join(raw.replace("\u00a0", " ").split())))
    ]
    parsed_totals = [item.shares for item in daily]
    if exec_buys and sorted(exec_buys) != sorted(parsed_totals):
        raise ValueError(
            f"NewsWeb ExecBuy-avstemming feilet: vedlegg={exec_buys}, parser={parsed_totals}"
        )
    return daily

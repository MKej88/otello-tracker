from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
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


def _economic_tuple(tokens: list[str], normalized: str) -> tuple[int, Decimal, Decimal] | None:
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

    punctuated: list[tuple[int, Decimal, Decimal]] = []
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
    return selected_pool[0]


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
    economic = _economic_tuple(tokens, normalized)
    if economic is None:
        return None
    shares, price, amount = economic
    return BuybackTrade(
        trade_date=_date(date_match.group(0)),
        trade_time=time_match.group(0),
        shares=shares,
        price_nok=price,
        amount_nok=amount,
    )


def _parse_undated_duplicate_time_line(line: str) -> BuybackTrade | None:
    """Recognize the pypdf defect where the date cell repeats the trade time.

    This function deliberately leaves the date blank. A date is assigned only by
    ``_recover_single_missing_trade_date`` when the canonical weekly period and the
    ExecBuy totals make the missing date unique.
    """
    normalized = " ".join(line.replace("\u00a0", " ").split())
    if not normalized:
        return None
    if _SELL_RE.match(normalized):
        raise ValueError("NewsWeb buyback-vedlegg inneholder OTEC-salg; krever kontroll")
    if not normalized.upper().startswith("B OTEC ") or _DATE_RE.search(normalized):
        return None

    time_matches = list(_TIME_RE.finditer(normalized))
    if len(time_matches) != 2 or time_matches[0].group(0) != time_matches[1].group(0):
        return None

    payload = normalized
    for match in reversed(time_matches):
        payload = payload[: match.start()] + " " + payload[match.end() :]
    tokens = " ".join(payload.split())[len("B OTEC ") :].split()
    economic = _economic_tuple(tokens, normalized)
    if economic is None:
        return None
    shares, price, amount = economic
    return BuybackTrade(
        trade_date="",
        trade_time=time_matches[0].group(0),
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


def _recover_single_missing_trade_date(
    text: str,
    trades: list[BuybackTrade],
    exec_buys: list[int],
    *,
    period_start: str,
    period_end: str,
) -> list[BuybackTrade]:
    undated = [
        parsed
        for raw in text.splitlines()
        if (parsed := _parse_undated_duplicate_time_line(raw)) is not None
    ]
    if not undated:
        return trades

    start = date.fromisoformat(period_start)
    end = date.fromisoformat(period_end)
    if end < start:
        raise ValueError("Ugyldig NewsWeb-ukesperiode for datoreparasjon")

    weekdays: list[str] = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            weekdays.append(current.isoformat())
        current += timedelta(days=1)

    known_dates = {item.trade_date for item in trades}
    missing_dates = [item for item in weekdays if item not in known_dates]
    if len(missing_dates) != 1:
        raise ValueError("NewsWeb manglende PDF-dato kan ikke utledes entydig fra ukesperioden")

    parsed_totals = [item.shares for item in aggregate_daily_buybacks(trades)]
    parsed_counter = Counter(parsed_totals)
    exec_counter = Counter(exec_buys)
    if parsed_counter - exec_counter:
        raise ValueError("NewsWeb datoreparasjon avviser ukjent allerede-parset dagsum")

    missing_exec = exec_counter - parsed_counter
    if sum(missing_exec.values()) != 1:
        raise ValueError("NewsWeb datoreparasjon krever nøyaktig én manglende ExecBuy-dagsum")
    expected_shares = next(missing_exec.elements())
    recovered_shares = sum(item.shares for item in undated)
    if recovered_shares != expected_shares:
        raise ValueError(
            "NewsWeb udaterte handler avstemmer ikke mot den manglende ExecBuy-dagsummen"
        )

    inferred_date = missing_dates[0]
    recovered = [
        BuybackTrade(
            trade_date=inferred_date,
            trade_time=item.trade_time,
            shares=item.shares,
            price_nok=item.price_nok,
            amount_nok=item.amount_nok,
        )
        for item in undated
    ]
    return [*trades, *recovered]


def parse_buyback_transaction_text(
    text: str,
    *,
    period_start: str | None = None,
    period_end: str | None = None,
) -> list[DailyBuybackTransaction]:
    trades = parse_buyback_trade_lines(text)
    daily = aggregate_daily_buybacks(trades)
    exec_buys = [
        _integer(match.group(1))
        for raw in text.splitlines()
        if (match := _EXEC_BUY_RE.match(" ".join(raw.replace("\u00a0", " ").split())))
    ]
    parsed_totals = [item.shares for item in daily]

    if exec_buys and sorted(exec_buys) != sorted(parsed_totals):
        if period_start is not None and period_end is not None:
            trades = _recover_single_missing_trade_date(
                text,
                trades,
                exec_buys,
                period_start=period_start,
                period_end=period_end,
            )
            daily = aggregate_daily_buybacks(trades)
            parsed_totals = [item.shares for item in daily]

    if exec_buys and sorted(exec_buys) != sorted(parsed_totals):
        raise ValueError(
            f"NewsWeb ExecBuy-avstemming feilet: vedlegg={exec_buys}, parser={parsed_totals}"
        )
    return daily

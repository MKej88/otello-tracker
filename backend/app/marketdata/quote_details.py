from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from statistics import mean
from typing import Any
from zoneinfo import ZoneInfo

from app.db.connection import get_connection

_SYMBOLS = {
    "OTEC": {"currency": "NOK", "source": "EURONEXT"},
    "BMOB3": {"currency": "BRL", "source": "B3"},
    "LIF": {"currency": "USD", "source": "YAHOO_FINANCE"},
}

THREE_MONTH_TRADING_SESSIONS = 63


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _metadata(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _meta_number(metadata: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        result = _number(metadata.get(key))
        if result is not None:
            return result
    return None


def _first_meta_number(rows: list[dict[str, Any]], *keys: str) -> float | None:
    """Return the first usable metadata value from rows in priority order."""
    for row in rows:
        result = _meta_number(_metadata(row.get("metadata_json")), *keys)
        if result is not None:
            return result
    return None


def _preferred_daily_rows(
    rows: list[dict[str, Any]], symbol: str
) -> list[dict[str, Any]]:
    by_date: dict[str, dict[str, Any]] = {}
    preferred_source = _SYMBOLS[symbol]["source"]
    for row in rows:
        day = str(row["trading_date"])
        current = by_date.get(day)
        priority = (
            int(row.get("series_priority") or 0),
            0 if row.get("source_code") == preferred_source else 1,
            (
                0
                if row.get("quality")
                in {"DIRECT", "HISTORICAL_EXPORT", "DELAYED_TRADE_SUM"}
                else 1
            ),
            -int(row.get("id") or 0),
        )
        if current is None or priority < current["_priority"]:
            by_date[day] = {**row, "_priority": priority}
    return [by_date[key] for key in sorted(by_date)]


def _latest_price(connection, symbol: str) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT mp.id, mp.trading_date, mp.observed_at, mp.price_type, mp.price,
               mp.currency, mp.quality, mp.metadata_json, s.code AS source_code
        FROM market_prices mp
        JOIN instruments i ON i.id=mp.instrument_id
        JOIN sources s ON s.id=mp.source_id
        WHERE i.symbol=? AND mp.price_type IN ('LAST','CLOSE')
        ORDER BY mp.trading_date DESC,
                 CASE WHEN mp.price_type='CLOSE' THEN 0 ELSE 1 END,
                 mp.observed_at DESC, mp.id DESC
        LIMIT 1
        """,
        (symbol,),
    ).fetchone()
    return dict(row) if row is not None else None


def _market_close(
    connection, symbol: str, before_date: str | None = None
) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT mp.id, mp.trading_date, mp.observed_at, mp.price, mp.quality,
               mp.metadata_json, s.code AS source_code
        FROM market_prices mp
        JOIN instruments i ON i.id=mp.instrument_id
        JOIN sources s ON s.id=mp.source_id
        WHERE i.symbol=? AND mp.price_type='CLOSE'
          AND (? IS NULL OR mp.trading_date < ?)
        ORDER BY mp.trading_date DESC,
                 CASE WHEN s.code=? THEN 0 ELSE 1 END,
                 CASE WHEN mp.quality='DIRECT' THEN 0 ELSE 1 END,
                 mp.id DESC
        LIMIT 1
        """,
        (symbol, before_date, before_date, _SYMBOLS[symbol]["source"]),
    ).fetchone()
    return dict(row) if row is not None else None


def _latest_close(
    connection, symbol: str, before_date: str | None = None
) -> dict[str, Any] | None:
    market = _market_close(connection, symbol, before_date)
    if symbol != "OTEC":
        return market

    activity_row = connection.execute(
        """
        SELECT ma.id, ma.trading_date, ma.last_price_nok AS price,
               ma.quality, ma.metadata_json, s.code AS source_code
        FROM market_activity ma
        JOIN instruments i ON i.id=ma.instrument_id
        JOIN sources s ON s.id=ma.source_id
        WHERE i.symbol='OTEC' AND ma.last_price_nok IS NOT NULL
          AND (? IS NULL OR ma.trading_date < ?)
        ORDER BY ma.trading_date DESC, ma.id DESC
        LIMIT 1
        """,
        (before_date, before_date),
    ).fetchone()
    activity = dict(activity_row) if activity_row is not None else None
    if activity is None:
        return market
    if market is None or str(activity["trading_date"]) >= str(market["trading_date"]):
        activity["close_basis"] = "COMPLETED_SESSION_LAST_TRADE"
        return activity
    market["close_basis"] = "OFFICIAL_CLOSE"
    return market


def _oslo_close_timestamp(trading_date: str) -> str:
    """Returner tidspunktet da den ordinære OTEC-handelen stengte."""
    local_close = datetime.combine(
        date.fromisoformat(trading_date),
        time(hour=16, minute=20),
        tzinfo=ZoneInfo("Europe/Oslo"),
    )
    return local_close.isoformat(timespec="seconds")


def _day_stats(connection, symbol: str, trading_date: str) -> dict[str, Any]:
    rows = [
        dict(row)
        for row in connection.execute(
            """
            SELECT mp.id, mp.price_type, mp.price, mp.observed_at, mp.metadata_json,
                   mp.quality, s.code AS source_code
            FROM market_prices mp
            JOIN instruments i ON i.id=mp.instrument_id
            JOIN sources s ON s.id=mp.source_id
            WHERE i.symbol=? AND mp.trading_date=? AND mp.price_type IN ('LAST','CLOSE','OPEN','HIGH','LOW')
            ORDER BY mp.observed_at ASC, mp.id ASC
            """,
            (symbol, trading_date),
        )
    ]
    if not rows:
        return {"open": None, "low": None, "high": None, "basis": "MISSING"}

    preferred = sorted(
        rows,
        key=lambda row: (
            0 if row.get("source_code") == _SYMBOLS[symbol]["source"] else 1,
            0 if row.get("price_type") == "CLOSE" else 1,
            -int(row.get("id") or 0),
        ),
    )
    open_value = _first_meta_number(preferred, "open_price", "open")
    low_value = _first_meta_number(preferred, "min_price", "low", "day_low")
    high_value = _first_meta_number(preferred, "max_price", "high", "day_high")
    if open_value is not None and low_value is not None and high_value is not None:
        return {
            "open": open_value,
            "low": low_value,
            "high": high_value,
            "basis": "EXCHANGE_SESSION_SUMMARY",
        }

    explicit: dict[str, float] = {}
    observed_prices: list[float] = []
    last_rows: list[dict[str, Any]] = []
    for row in rows:
        value = _number(row.get("price"))
        if value is None:
            continue
        observed_prices.append(value)
        if row["price_type"] in {"OPEN", "HIGH", "LOW"}:
            explicit[str(row["price_type"])] = value
        if row["price_type"] == "LAST":
            last_rows.append(row)

    if symbol == "OTEC":
        activity_row = connection.execute(
            """
            SELECT ma.last_price_nok AS price
            FROM market_activity ma
            JOIN instruments i ON i.id=ma.instrument_id
            WHERE i.symbol='OTEC' AND ma.trading_date=?
              AND ma.last_price_nok IS NOT NULL
            ORDER BY ma.id DESC
            LIMIT 1
            """,
            (trading_date,),
        ).fetchone()
        activity_price = _number(activity_row["price"] if activity_row else None)
        if activity_price is not None:
            observed_prices.append(activity_price)

    open_value = open_value if open_value is not None else explicit.get("OPEN")
    low_value = low_value if low_value is not None else explicit.get("LOW")
    high_value = high_value if high_value is not None else explicit.get("HIGH")

    if symbol == "LIF":
        return {
            "open": open_value,
            "low": low_value,
            "high": high_value,
            "basis": (
                "STORED_SESSION_DATA"
                if any(
                    value is not None for value in (open_value, low_value, high_value)
                )
                else "CLOSE_ONLY"
            ),
        }

    if open_value is None and last_rows:
        open_value = _number(last_rows[0].get("price"))
    if low_value is None and observed_prices:
        low_value = min(observed_prices)
    if high_value is None and observed_prices:
        high_value = max(observed_prices)
    return {
        "open": open_value,
        "low": low_value,
        "high": high_value,
        "basis": "OBSERVED_TRADES" if symbol == "OTEC" else "STORED_MARKET_PRICES",
    }


def _daily_history(connection, symbol: str, as_of_date: str) -> list[dict[str, Any]]:
    start = (date.fromisoformat(as_of_date) - timedelta(days=365)).isoformat()
    market_rows = [
        {**dict(row), "series_priority": 1 if symbol == "OTEC" else 0}
        for row in connection.execute(
            """
            SELECT mp.id, mp.trading_date, mp.price, mp.quality, mp.metadata_json,
                   s.code AS source_code
            FROM market_prices mp
            JOIN instruments i ON i.id=mp.instrument_id
            JOIN sources s ON s.id=mp.source_id
            WHERE i.symbol=? AND mp.price_type='CLOSE'
              AND mp.trading_date BETWEEN ? AND ?
            ORDER BY mp.trading_date ASC, mp.id ASC
            """,
            (symbol, start, as_of_date),
        )
    ]
    if symbol != "OTEC":
        return _preferred_daily_rows(market_rows, symbol)

    activity_rows = [
        {**dict(row), "series_priority": 0}
        for row in connection.execute(
            """
            SELECT ma.id, ma.trading_date, ma.last_price_nok AS price,
                   ma.quality, ma.metadata_json, s.code AS source_code
            FROM market_activity ma
            JOIN instruments i ON i.id=ma.instrument_id
            JOIN sources s ON s.id=ma.source_id
            WHERE i.symbol='OTEC' AND ma.last_price_nok IS NOT NULL
              AND ma.trading_date BETWEEN ? AND ?
            ORDER BY ma.trading_date ASC, ma.id ASC
            """,
            (start, as_of_date),
        )
    ]
    return _preferred_daily_rows([*market_rows, *activity_rows], symbol)


def _volume_summary(volume_rows: list[tuple[str, float]], basis: str) -> dict[str, Any]:
    values = [value for _, value in volume_rows]
    average = mean(values) if values else None
    return {
        "latest": values[0] if values else None,
        "latest_date": volume_rows[0][0] if volume_rows else None,
        "average_3m": average,
        "average_sessions": len(values),
        "latest_above_average": (values[0] > average if average is not None else None),
        "unit": "shares",
        "basis": basis,
    }


def _volume_stats(
    connection,
    symbol: str,
    history: list[dict[str, Any]],
    latest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if symbol == "OTEC":
        rows = [
            dict(row)
            for row in connection.execute(
                """
                SELECT trading_date, volume_shares
                FROM market_activity ma
                JOIN instruments i ON i.id=ma.instrument_id
                WHERE i.symbol='OTEC' AND ma.volume_shares IS NOT NULL
                ORDER BY trading_date DESC, ma.id DESC
                LIMIT 126
                """
            )
        ]
        deduped: dict[str, float] = {}
        for row in rows:
            if row["trading_date"] in deduped:
                continue
            value = _number(row.get("volume_shares"))
            if value is not None and value >= 0:
                deduped[str(row["trading_date"])] = value
            if len(deduped) >= THREE_MONTH_TRADING_SESSIONS:
                break
        return _volume_summary(
            list(deduped.items()),
            basis="EURONEXT_DAILY_ACTIVITY",
        )

    volume_rows: list[tuple[str, float]] = []
    for row in reversed(history):
        meta = _metadata(row.get("metadata_json"))
        value = _meta_number(meta, "volume_shares", "quantity_shares")
        if value is not None and value >= 0:
            volume_rows.append((str(row["trading_date"]), value))
        if len(volume_rows) >= THREE_MONTH_TRADING_SESSIONS:
            break

    values = [value for _, value in volume_rows]
    average = mean(values) if values else None
    latest_value = volume_rows[0][1] if volume_rows else None
    latest_date = volume_rows[0][0] if volume_rows else None
    basis = (
        "B3_COTAHIST_QUANTITY"
        if symbol == "BMOB3"
        else "STORED_MARKET_PRICE_METADATA"
    )
    source = "B3" if symbol == "BMOB3" else None
    provisional = False

    if symbol == "BMOB3" and latest is not None:
        latest_meta = _metadata(latest.get("metadata_json"))
        intraday_volume = _meta_number(latest_meta, "volume_shares")
        if (
            intraday_volume is not None
            and intraday_volume >= 0
            and latest_meta.get("volume_provisional") is True
            and latest_meta.get("volume_source") == "YAHOO_FINANCE"
        ):
            latest_value = intraday_volume
            latest_date = str(latest.get("trading_date"))
            basis = "YAHOO_FINANCE_INTRADAY"
            source = "YAHOO_FINANCE"
            provisional = True

    result = {
        "latest": latest_value,
        "latest_date": latest_date,
        "average_3m": average,
        "average_sessions": len(values),
        "latest_above_average": (
            latest_value > average
            if latest_value is not None and average is not None
            else None
        ),
        "unit": "shares",
        "basis": basis,
    }
    if symbol == "BMOB3":
        result["source"] = source
        result["provisional"] = provisional
    return result


def _range_52w(history: list[dict[str, Any]]) -> dict[str, Any]:
    lows: list[float] = []
    highs: list[float] = []
    used_session_range = False
    for row in history:
        close = _number(row.get("price"))
        if close is None:
            continue
        meta = _metadata(row.get("metadata_json"))
        low = _meta_number(meta, "low", "min_price", "day_low")
        high = _meta_number(meta, "high", "max_price", "day_high")
        lows.append(low if low is not None else close)
        highs.append(high if high is not None else close)
        used_session_range = used_session_range or low is not None or high is not None
    return {
        "low": min(lows) if lows else None,
        "high": max(highs) if highs else None,
        "sessions": len(lows),
        "basis": (
            "SESSION_HIGH_LOW_WITH_CLOSE_FALLBACK"
            if used_session_range
            else "DAILY_CLOSE"
        ),
    }


def _quote(connection, symbol: str) -> dict[str, Any]:
    latest = _latest_price(connection, symbol)
    if latest is None:
        return {"ready": False, "symbol": symbol, "reason": "missing_market_price"}
    current_close = _latest_close(connection, symbol) if symbol == "OTEC" else None
    if current_close and str(current_close["trading_date"]) >= str(
        latest["trading_date"]
    ):
        latest = {
            **current_close,
            "price_type": "CLOSE",
            "observed_at": _oslo_close_timestamp(str(current_close["trading_date"])),
        }

    trading_date = str(latest["trading_date"])
    history = _daily_history(connection, symbol, trading_date)
    latest_close = _latest_close(
        connection,
        symbol,
        trading_date if symbol == "OTEC" else None,
    )
    return {
        "ready": True,
        "symbol": symbol,
        "currency": _SYMBOLS[symbol]["currency"],
        "source": latest.get("source_code") or _SYMBOLS[symbol]["source"],
        "last": _number(latest.get("price")),
        "last_price_type": latest.get("price_type"),
        "last_updated_at": latest.get("observed_at"),
        "trading_date": trading_date,
        "session": _day_stats(connection, symbol, trading_date),
        "last_close": {
            "price": _number(latest_close.get("price")) if latest_close else None,
            "date": latest_close.get("trading_date") if latest_close else None,
            "source": latest_close.get("source_code") if latest_close else None,
            "basis": latest_close.get("close_basis") if latest_close else None,
        },
        "volume": _volume_stats(connection, symbol, history, latest),
        "range_52w": _range_52w(history),
    }


def market_quote_details(database_path: str | None = None) -> dict[str, Any]:
    with get_connection(database_path) as connection:
        quotes = {symbol: _quote(connection, symbol) for symbol in _SYMBOLS}
    return {
        "ready": any(item.get("ready") for item in quotes.values()),
        "symbols": quotes,
        "methodology": {
            "average_volume": (
                "Gjennomsnitt av inntil 63 siste tilgjengelige handelssesjoner, "
                "tilsvarende omtrent tre måneder."
            ),
            "range_52w": (
                "52-ukers intervallet bruker offisiell dags høy/lav når den finnes "
                "i lagret kilde, ellers verifisert fullført-dags slutt-/sistehandel."
            ),
            "otec_session": (
                "OTEC dagens åpning/lav/høy er basert på direkte Euronext-handler "
                "lagret av den forsinkede feeden når full offisiell "
                "sesjonssummering ikke finnes."
            ),
            "otec_close": (
                "OTEC siste sluttkurs bruker den nyeste av eksplisitt CLOSE og "
                "siste handel fra fullført Euronext-dagsserie."
            ),
            "life360": (
                "Life360/LIF bruker lagrede NASDAQ-sluttkurser i USD fra Yahoo "
                "Finance. Intradag åpning/lav/høy og volum vises bare når slike "
                "data faktisk er lagret."
            ),
        },
    }

from . import enrichment as _enrichment
from .cash_sync import sync_newsweb_daily_buyback_cash
from .client import (
    NewsWebAttachment,
    NewsWebMessage,
    discover_otec_messages,
    fetch_attachment,
    fetch_message,
)
from .trade_parser import parse_buyback_transaction_text

# NewsWeb has emitted several historical PDF layouts. Keep message/enrichment policy in
# one module, but inject the independently tested arithmetic trade parser so both the
# collector and public package API use the same strict implementation.
_enrichment.parse_buyback_transaction_text = parse_buyback_transaction_text
collect_newsweb_buybacks = _enrichment.collect_newsweb_buybacks
newsweb_buyback_status = _enrichment.newsweb_buyback_status

__all__ = [
    "NewsWebAttachment",
    "NewsWebMessage",
    "collect_newsweb_buybacks",
    "discover_otec_messages",
    "fetch_attachment",
    "fetch_message",
    "newsweb_buyback_status",
    "parse_buyback_transaction_text",
    "sync_newsweb_daily_buyback_cash",
]

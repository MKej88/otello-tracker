from __future__ import annotations

"""Bakoverkompatibel importsti for eldre Cloudflare Workflow-instansar.

Ny produksjonskode skal bruke ``bemobi_web_refresh_runtime``. Denne filen beholdes
midlertidig fordi durable Workflow-instansar kan gjenopptas mot en eldre modulsti.
"""

from bemobi_web_refresh_runtime import (
    _ensure_consensus_event,
    _snapshot_payload,
    _store_forward_snapshot,
    parse_forward_consensus_html,
    refresh_bemobi_web,
    sync_marketscreener_consensus,
)

__all__ = [
    "_ensure_consensus_event",
    "_snapshot_payload",
    "_store_forward_snapshot",
    "parse_forward_consensus_html",
    "refresh_bemobi_web",
    "sync_marketscreener_consensus",
]

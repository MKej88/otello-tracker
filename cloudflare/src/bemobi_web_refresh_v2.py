"""Bakoverkompatibel importsti for eldre Cloudflare Workflow-instansar.

Ny produksjonskode skal bruke ``bemobi_web_refresh_runtime``. Denne filen beholdes
midlertidig fordi durable Workflow-instansar kan gjenopptas mot en eldre modulsti.
"""

from __future__ import annotations

from bemobi_web_refresh_runtime import _ensure_consensus_event, refresh_bemobi_web

__all__ = ["_ensure_consensus_event", "refresh_bemobi_web"]

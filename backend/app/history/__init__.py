from __future__ import annotations

import hashlib
import json
from functools import lru_cache

from app.db.runtime_state import get_runtime_state, set_runtime_state
from app.history.curated import history_status as _history_status
from app.history.curated import load_manifest
from app.history.curated import seed_curated_history as _seed_curated_history
from app.history.option_program import load_option_program_manifest
from app.history.other_net_assets import (
    load_other_net_assets_manifest,
    seed_other_net_assets_reported,
)
from app.history.share_capital_2022 import (
    load_2022_share_capital_corrections,
    seed_2022_share_capital_anchors,
)
from app.history.share_capital_2025 import (
    load_2025_share_capital_corrections,
    seed_2025_share_capital_anchors,
)

_CURATED_STATE_KEY = "curated_seed_fingerprint"


@lru_cache(maxsize=1)
def curated_manifest_version() -> str:
    return str(load_manifest()["version"])


@lru_cache(maxsize=1)
def curated_seed_fingerprint() -> str:
    """Hash every static manifest that affects curated facts or derived NAV inputs."""
    payload = {
        "base": load_manifest(),
        "share_capital_2022": load_2022_share_capital_corrections(),
        "share_capital_2025": load_2025_share_capital_corrections(),
        "other_net_assets": load_other_net_assets_manifest(),
        "option_program": load_option_program_manifest(),
    }
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def seed_curated_history(database_path: str | None = None) -> dict:
    result = _seed_curated_history(database_path)
    capital_2022 = seed_2022_share_capital_anchors(database_path)
    capital_2025 = seed_2025_share_capital_anchors(database_path)
    other_net_assets = seed_other_net_assets_reported(database_path)
    result["manifest_version"] = capital_2022["manifest_version"]
    result["share_capital_corrections"] = {
        "2022": capital_2022,
        "2025": capital_2025,
    }
    result["other_net_assets"] = other_net_assets
    result["option_program_version"] = load_option_program_manifest()["version"]
    set_runtime_state(_CURATED_STATE_KEY, curated_seed_fingerprint(), database_path)
    return result


def seed_curated_history_if_needed(database_path: str | None = None) -> dict:
    """Avoid rewriting immutable curated rows on every fast refresh."""
    fingerprint = curated_seed_fingerprint()
    if get_runtime_state(_CURATED_STATE_KEY, database_path) == fingerprint:
        return {
            "skipped": True,
            "reason": "curated_manifests_unchanged",
            "fingerprint": fingerprint,
            "manifest_version": curated_manifest_version(),
        }
    result = seed_curated_history(database_path)
    result["fingerprint"] = fingerprint
    return result


def history_status(database_path: str | None = None) -> dict:
    result = _history_status(database_path)
    corrections_2022 = load_2022_share_capital_corrections()
    corrections_2025 = load_2025_share_capital_corrections()
    rows = [*corrections_2022["share_counts"], *corrections_2025["share_counts"]]
    ona_manifest = load_other_net_assets_manifest()
    option_manifest = load_option_program_manifest()
    result["manifest_version"] = corrections_2022["version"]
    result["effective_share_capital_corrections"] = {
        "count": len(rows),
        "from": min(row["as_of_date"] for row in rows),
        "to": max(row["as_of_date"] for row in rows),
    }
    result["full_nav_report_anchors"] = {
        "count": len(ona_manifest["anchors"]),
        "from": ona_manifest["anchors"][0]["as_of_date"],
        "to": ona_manifest["anchors"][-1]["as_of_date"],
        "known_gaps": ona_manifest.get("known_gaps", []),
    }
    result["option_program"] = {
        "version": option_manifest["version"],
        "grant_date": option_manifest["program"]["grant_date"],
        "option_count": option_manifest["program"]["option_count"],
        "strike_price_nok": option_manifest["program"]["strike_price_nok"],
    }
    return result


__all__ = [
    "curated_manifest_version",
    "curated_seed_fingerprint",
    "seed_curated_history",
    "seed_curated_history_if_needed",
    "history_status",
]

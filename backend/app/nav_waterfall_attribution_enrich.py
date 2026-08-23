from __future__ import annotations

from typing import Any

from app.db.connection import get_connection
from app.nav_waterfall_attribution import (
    _bemobi_attribution,
    _component_amount_nok,
    _life360_attribution,
    apply_market_attribution,
)


def enrich_nav_waterfall(
    result: dict[str, Any],
    *,
    database_path: str | None = None,
) -> dict[str, Any]:
    """Add market-driver explanations on top of an already settled waterfall."""
    if not result.get("ready"):
        return result

    anchor_date = str(result["anchor_date"])
    as_of_date = str(result["as_of_date"])
    bemobi_component = next(
        (item for item in result.get("components") or [] if str(item.get("key")) == "bemobi"),
        None,
    )
    bemobi = None
    if bemobi_component is not None:
        with get_connection(database_path) as connection:
            bemobi = _bemobi_attribution(
                connection,
                anchor_date=anchor_date,
                as_of_date=as_of_date,
                expected_change_nok=_component_amount_nok(bemobi_component),
            )

    life360 = _life360_attribution(as_of_date=as_of_date, database_path=database_path)
    return apply_market_attribution(
        result,
        bemobi_attribution=bemobi,
        life360_attribution=life360,
    )

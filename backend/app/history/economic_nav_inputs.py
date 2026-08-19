from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.db.connection import get_connection
from app.db.repository import create_source_document

DATA_PATH = Path(__file__).with_name("data") / "economic_nav_inputs.json"


def load_economic_nav_inputs_manifest() -> dict[str, Any]:
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def _manifest_sha256(manifest: dict[str, Any]) -> str:
    raw = json.dumps(
        manifest,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def seed_economic_nav_inputs(database_path: str | None = None) -> dict[str, Any]:
    """Persist source-backed economic-NAV assumptions and FX validation outcomes."""
    manifest = load_economic_nav_inputs_manifest()
    manifest_sha = _manifest_sha256(manifest)
    documents = manifest["documents"]
    written: list[int] = []

    with get_connection(database_path) as connection:
        for item in manifest["operating_cost_anchors"]:
            source = documents[item["source_key"]]
            metadata = {
                "economic_nav_input_version": manifest["version"],
                "manifest_sha256": manifest_sha,
                "input_kind": "OPERATING_COST_ANCHOR",
                "scenario": item["scenario"],
                "effective_from": item["effective_from"],
                "source_period": item["source_period"],
                "source_period_start": item["source_period_start"],
                "source_period_end": item["source_period_end"],
                "period_days": int(item["period_days"]),
                "amount_usd": str(item["amount_usd"]),
                "source_measure": item["source_measure"],
                "source_locator": item["source_locator"],
                "notes": item.get("notes"),
                "curated": True,
            }
            document_id = create_source_document(
                connection,
                source_code=source["source_code"],
                external_id=(
                    f"economic-nav-cost:{item['effective_from']}:"
                    f"{str(item['scenario']).lower()}"
                ),
                document_type="ECONOMIC_NAV_COST_ANCHOR",
                title=(
                    f"Economic NAV operating-cost anchor {item['scenario']} "
                    f"from {item['effective_from']}"
                ),
                url=source["url"],
                published_at=f"{item['effective_from']}T00:00:00Z",
                metadata=metadata,
            )
            written.append(document_id)

        for item in manifest["cash_fx_exposure_anchors"]:
            total = Decimal(str(item["total_cash_usd"]))
            exposures = item["exposures"]
            exposure_total = sum(
                (Decimal(str(row["usd_equivalent"])) for row in exposures),
                Decimal("0"),
            )
            if exposure_total != total:
                raise ValueError(
                    f"Cash FX exposure {item['as_of_date']} does not reconcile: "
                    f"{exposure_total} != {total}"
                )
            currencies = [str(row["currency"]).upper() for row in exposures]
            if len(currencies) != len(set(currencies)):
                raise ValueError(f"Duplicate cash FX exposure currency for {item['as_of_date']}")
            if any(currency not in {"NOK", "USD", "BRL", "UNALLOCATED"} for currency in currencies):
                raise ValueError(f"Unsupported cash FX exposure currency for {item['as_of_date']}")

            source = documents[item["source_key"]]
            allocation_quality = (
                "PARTIAL_SOURCE_BACKED" if "UNALLOCATED" in currencies else "FULL_SOURCE_BACKED"
            )
            metadata = {
                "economic_nav_input_version": manifest["version"],
                "manifest_sha256": manifest_sha,
                "input_kind": "CASH_FX_EXPOSURE_ANCHOR",
                "as_of_date": item["as_of_date"],
                "total_cash_usd": str(item["total_cash_usd"]),
                "exposures": exposures,
                "source_locator": item["source_locator"],
                "notes": item.get("notes"),
                "curated": True,
                "allocation_quality": allocation_quality,
                "policy": "REVALUE_SOURCE_BACKED_USD_BRL_KEEP_NOK_FIXED_KEEP_UNALLOCATED_FIXED",
            }
            document_id = create_source_document(
                connection,
                source_code=source["source_code"],
                external_id=f"economic-nav-cash-fx:{item['as_of_date']}",
                document_type="ECONOMIC_NAV_CASH_FX_ANCHOR",
                title=f"Economic NAV cash FX exposure anchor {item['as_of_date']}",
                url=source["url"],
                published_at=f"{item['as_of_date']}T00:00:00Z",
                metadata=metadata,
            )
            written.append(document_id)

        for item in manifest.get("fx_backtest_outcomes", []):
            source = documents[item["source_key"]]
            metadata = {
                "economic_nav_input_version": manifest["version"],
                "manifest_sha256": manifest_sha,
                "input_kind": "FX_BACKTEST_OUTCOME",
                "period_start": item["period_start"],
                "period_end": item["period_end"],
                "cash_fx_effect_usd": str(item["cash_fx_effect_usd"]),
                "pnl_fx_result_usd": str(item["pnl_fx_result_usd"]),
                "other_balance_sheet_fx_usd": (
                    str(item["other_balance_sheet_fx_usd"])
                    if item.get("other_balance_sheet_fx_usd") is not None
                    else None
                ),
                "source_locator": item["source_locator"],
                "notes": item.get("notes"),
                "curated": True,
                "primary_validation_target": "cash_fx_effect_usd",
            }
            document_id = create_source_document(
                connection,
                source_code=source["source_code"],
                external_id=f"fx-backtest-outcome:{item['period_end']}",
                document_type="ECONOMIC_NAV_FX_BACKTEST_OUTCOME",
                title=f"FX backtest reported outcome {item['period_end']}",
                url=source["url"],
                published_at=f"{item['period_end']}T00:00:00Z",
                metadata=metadata,
            )
            written.append(document_id)

        connection.commit()

    return {
        "manifest_version": manifest["version"],
        "manifest_sha256": manifest_sha,
        "documents": len(written),
        "operating_cost_anchors": len(manifest["operating_cost_anchors"]),
        "cash_fx_exposure_anchors": len(manifest["cash_fx_exposure_anchors"]),
        "fx_backtest_outcomes": len(manifest.get("fx_backtest_outcomes", [])),
    }

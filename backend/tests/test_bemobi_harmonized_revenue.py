from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
if str(CLOUDFLARE_SRC) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE_SRC))

import bemobi_cvm_post_result as post_result  # noqa: E402


class _Repository:
    def __init__(self) -> None:
        self.updated_payload: dict | None = None

    async def first(self, sql: str, params=()):
        assert params == ("3Q26",)
        if "fact_type='TTM_QUARTER'" in sql:
            return {
                "id": 77,
                "payload_json": json.dumps(
                    {
                        "period": "3Q26",
                        "reported_revenue_mbrl": 520.0,
                    }
                ),
            }
        if "fact_type='RESULT'" in sql:
            return {
                "payload_json": json.dumps(
                    {
                        "period": "3Q26",
                        "period_end": "2026-09-30",
                        "adjusted_net_revenue_mbrl": 240.0,
                    }
                ),
                "source_name": "CVM",
                "source_url": "https://example.test/bemobi-3q26.pdf",
                "published_date": "2026-11-10",
            }
        raise AssertionError(sql)

    async def run(self, sql: str, params=()):
        assert "UPDATE bemobi_investor_facts" in sql
        self.updated_payload = json.loads(params[0])
        assert params[1] == 77
        return None


def test_harmonized_revenue_is_stored_separately_from_statutory_cvm_revenue() -> None:
    repository = _Repository()
    result = asyncio.run(
        post_result._merge_harmonized_revenue_from_result(repository, period="3Q26")
    )

    assert result == {"status": "updated", "rows_written": 1, "value_mbrl": 240.0}
    assert repository.updated_payload is not None
    assert repository.updated_payload["reported_revenue_mbrl"] == 520.0
    assert repository.updated_payload["harmonized_net_revenue_mbrl"] == 240.0
    assert repository.updated_payload["harmonized_net_revenue_source"] == "Bemobi result release via CVM"
    assert repository.updated_payload["harmonized_net_revenue_source_url"] == "https://example.test/bemobi-3q26.pdf"
    assert repository.updated_payload["harmonized_net_revenue_quality"] == "OFFICIAL_RESULT_HARMONIZED"


def test_harmonized_revenue_seed_reproduces_current_836m_ttm() -> None:
    migration = (ROOT / "cloudflare/migrations/0024_bemobi_harmonized_revenue_seed.sql").read_text(
        encoding="utf-8"
    )
    values = [
        float(item)
        for item in re.findall(r"'\$\.harmonized_net_revenue_mbrl',\s*([0-9.]+)", migration)
    ]
    assert values == [187.5, 199.2, 222.0, 227.3]
    assert sum(values) == 836.0


def test_clean_bemobi_page_keeps_harmonized_revenue_as_primary_investor_metric() -> None:
    page = (ROOT / "frontend/src/BemobiPageBase.tsx").read_text(encoding="utf-8")

    assert "adjusted_net_revenue_mbrl" in page
    assert "quarter.harmonized_net_revenue_mbrl ?? quarter.reported_revenue_mbrl ?? null" in page
    assert "Siste fire rapporterte kvartaler" in page

    # The statutory CVM revenue remains available in the payload as a fallback/control,
    # but the clean investor page no longer renders a separate reconciliation panel.
    assert "reported_revenue_mbrl" in page
    assert "Regnskapsført omsetning TTM · CVM 3.01 · kontroll" not in page
    assert "M4U-bruttoføringen" not in page

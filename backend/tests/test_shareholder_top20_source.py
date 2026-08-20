from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
if str(CLOUDFLARE_SRC) not in sys.path:
    sys.path.insert(0, str(CLOUDFLARE_SRC))

from shareholder_top20_source import (  # noqa: E402
    EXPECTED_ROWS,
    fetch_top20,
    parse_accessibility_tree,
    parse_markdown,
)


def _cells(rank: int) -> list[str]:
    shares = 4_100_000 - rank * 100_000
    return [f"Investor {rank} AS", f"{shares:,}", "5.00%", "4.25%", "Comp.", "NOR"]


def _html() -> str:
    rows = []
    for rank in range(1, EXPECTED_ROWS + 1):
        cells = "".join(f"<td>{value}</td>" for value in _cells(rank))
        rows.append(f"<tr>{cells}</tr>")
    return "<table><tbody>" + "".join(rows) + "</tbody></table>"


def test_accessibility_tree_parses_top20_rows() -> None:
    tree = {
        "role": "RootWebArea",
        "name": "Shareholders",
        "children": [
            {
                "role": "row",
                "children": [
                    {"role": "cell", "name": value}
                    for value in _cells(rank)
                ],
            }
            for rank in range(1, EXPECTED_ROWS + 1)
        ],
    }
    rows = parse_accessibility_tree(tree)
    assert len(rows) == 20
    assert rows[0]["rank"] == 1
    assert rows[0]["shareholder_name"] == "Investor 1 AS"
    assert rows[0]["country"] == "NOR"
    assert rows[-1]["rank"] == 20


def test_markdown_table_parses_top20_rows() -> None:
    lines = ["| Shareholder | Shares | Top20 | Total | Type | Country |", "|---|---:|---:|---:|---|---|"]
    lines.extend("| " + " | ".join(_cells(rank)) + " |" for rank in range(1, 21))
    rows = parse_markdown("\n".join(lines))
    assert len(rows) == 20
    assert rows[1]["shareholder_name"] == "Investor 2 AS"
    assert rows[1]["shares"] == 3_900_000


def test_legacy_static_html_wins_without_browser_run() -> None:
    class Response:
        ok = True
        status = 200

        async def text(self):
            return _html()

    async def fake_fetch(url, **kwargs):
        assert "key=opera" in url
        return Response()

    class Browser:
        async def quickAction(self, *args, **kwargs):  # pragma: no cover - must never run
            raise AssertionError("Browser Run should not be used when legacy HTML has 20 rows")

    rows, metadata = asyncio.run(fetch_top20(Browser(), fetcher=fake_fetch))
    assert len(rows) == 20
    assert metadata["method"] == "OMS_LEGACY_STATIC_HTML"
    assert metadata["browser_calls"] == 0
    assert metadata["extraction_url"].endswith("key=opera&lang=en")

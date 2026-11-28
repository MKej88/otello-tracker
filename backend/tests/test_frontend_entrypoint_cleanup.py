from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "frontend" / "src"


def test_legacy_frontend_components_are_not_reintroduced():
    retired = ("App", "HistoryPage", "DeferredDiagnostics", "EconomicNavPanel",
               "NavWaterfallPanel", "ReportStatusPanel", "RuntimeStatusPanel", "MarketQuotePanel")
    for name in retired:
        assert not (SRC / f"{name}.tsx").exists(), name
    # Check literal imports, dynamic imports and re-exports throughout src.
    imports = re.compile(
        r"""(?:from\s*|import\s*\(\s*|import\s*)['"](?:\./|[^'"]*/)(App|HistoryPage|DeferredDiagnostics|EconomicNavPanel|NavWaterfallPanel|ReportStatusPanel|RuntimeStatusPanel|MarketQuotePanel)(?:\.tsx?)?['"]"""
    )
    for path in SRC.rglob("*"):
        if path.suffix in {".ts", ".tsx", ".js", ".jsx"}:
            assert not imports.search(path.read_text(encoding="utf-8")), str(path)


def test_active_frontend_entrypoint_and_routes_remain_wired():
    main = (SRC / "main.tsx").read_text(encoding="utf-8")
    investor = (SRC / "InvestorApp.tsx").read_text(encoding="utf-8")
    assert 'import InvestorApp from "./InvestorApp";' in main
    assert "<InvestorApp />" in main
    for page in ("EstimatedHistoryPage", "NavPageV2", "DataQualityPage", "BemobiPage"):
        assert (SRC / f"{page}.tsx").exists()
        assert f'import("./{page}")' in investor
        assert f"<{page} />" in investor


def test_retired_stylesheets_are_not_imported_or_reintroduced():
    retired = (
        "economic-nav.css", "history-page.css", "nav-waterfall.css",
        "report-status.css", "runtime-status.css", "market-quote-panel.css",
    )
    for name in retired:
        assert not (SRC / name).exists(), name
    sources = [path for path in SRC.rglob("*")
               if path.suffix in {".ts", ".tsx", ".js", ".jsx", ".css"}]
    sources.append(SRC.parent / "index.html")
    for path in sources:
        source = path.read_text(encoding="utf-8")
        for name in retired:
            assert name not in source, (path, name)

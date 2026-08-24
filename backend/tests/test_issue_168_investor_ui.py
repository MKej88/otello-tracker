from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend" / "src"


def test_issue_168_uses_new_investor_app_without_global_diagnostics() -> None:
    main = (FRONTEND / "main.tsx").read_text(encoding="utf-8")
    app = (FRONTEND / "InvestorApp.tsx").read_text(encoding="utf-8")
    assert 'import InvestorApp from "./InvestorApp"' in main
    assert "import DeferredDiagnostics" not in main
    assert "<InvestorApp />" in main
    assert '"Datakvalitet"' in app
    assert "ESTIMERT NAV" in app


def test_issue_168_has_all_requested_periods_and_estimated_nav_views() -> None:
    periods = (FRONTEND / "investorPeriods.ts").read_text(encoding="utf-8")
    nav = (FRONTEND / "NavPageV2.tsx").read_text(encoding="utf-8")
    history = (FRONTEND / "EstimatedHistoryPage.tsx").read_text(encoding="utf-8")
    for label in ("1 M", "3 M", "6 M", "YTD", "1 ÅR", "3 ÅR"):
        assert label in periods
    assert "Hva består Estimert NAV av i dag?" in nav
    assert "Hva har flyttet Estimert NAV?" in nav
    assert "Nettoeffekt" in nav
    assert "start_per_share_nok" in nav
    assert "current_per_share_nok" in nav
    assert "driverNetTable" in nav
    assert "driverBarTrack" not in nav
    assert "Rabatt til Estimert NAV" in history
    assert "axisLabel" in history
    assert "Rabatt / premie" in history


def test_issue_168_moves_technical_information_to_data_quality() -> None:
    page = (FRONTEND / "DataQualityPage.tsx").read_text(encoding="utf-8")
    assert "Drift, ferskhet og kildekontroll" in page
    assert "Automatisk rapportinnlesing" in page
    assert "BemobiSourceStatusPanel" in page
    assert "Produksjonsstatus" not in page
    assert "Rapportkontroll" not in page

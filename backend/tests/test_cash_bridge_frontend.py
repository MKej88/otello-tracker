from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "frontend" / "src" / "CashPage.tsx"
CASH_OVERRIDES = ROOT / "frontend" / "src" / "cash-surface-overrides.css"


def test_cash_page_shows_how_estimated_cash_is_derived() -> None:
    source = PAGE.read_text(encoding="utf-8")

    for token in (
        "OTELLO CASH-MODELL",
        "Estimert cash i dag",
        "Rapportert kontantbeholdning",
        "cashBridge?.movements",
        "movement.label",
        "Endring siden siste rapport",
        "Siste rapporterte kontantbeholdning",
        "cashBridge?.report_date",
        "cashBridge?.cash_per_share_nok",
    ):
        assert token in source

    assert "signedMoneyM(movement.amount_mnok)" in source
    assert "movementTone(movement.amount_mnok)" in source
    assert "movementTone(cashBridge?.change_since_report_mnok)" in source
    assert "Kontantkvalitet</span>" not in source
    assert "Kalibrering</span>" not in source


def test_cash_bridge_preserves_positive_and_negative_colors_inside_cards() -> None:
    styles = CASH_OVERRIDES.read_text(encoding="utf-8")

    assert ".investorPage.cashPage .cashBridgeRows strong.positive" in styles
    assert "color: var(--ot-positive);" in styles
    assert ".investorPage.cashPage .cashBridgeRows strong.negative" in styles
    assert "color: var(--ot-negative);" in styles

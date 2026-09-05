from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "frontend" / "src" / "CashPage.tsx"


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
    assert "Kontantkvalitet</span>" not in source
    assert "Kalibrering</span>" not in source

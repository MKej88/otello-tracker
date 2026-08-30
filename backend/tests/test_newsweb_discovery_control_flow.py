"""Risikobaserte tester av kontrollflyten i NewsWeb-søk."""

from datetime import date

import pytest

from app.newsweb import client
from app.newsweb.client import NewsWebMessage


def _message(
    message_id: int,
    published_at: str,
    *,
    corrected_by_message_id: int = 0,
    title: str = "Otello-melding",
) -> NewsWebMessage:
    return NewsWebMessage(
        message_id=message_id,
        news_id=message_id + 1_000,
        title=title,
        body="",
        issuer_id=client.OTEC_ISSUER_ID,
        issuer_sign=client.OTEC_SIGN,
        issuer_name="Otello Corporation ASA",
        published_at=published_at,
        markets=("XOSL",),
        category_ids=(1007,),
        attachments=(),
        corrected_by_message_id=corrected_by_message_id,
        correction_for_message_id=0,
        client_announcement_id=None,
    )


def test_overflow_deler_datovindu_uten_hull_og_beholder_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Viktigst: et fullt API-vindu skal ikke gi stille tap av meldinger."""
    calls: list[tuple[date, date, str, int]] = []
    july_1 = _message(101, "2026-07-01T08:00:00Z")
    july_2 = _message(102, "2026-07-02T08:00:00Z")
    july_3 = _message(103, "2026-07-03T08:00:00Z")

    def fake_list_window(
        start: date,
        end: date,
        *,
        message_title: str,
        timeout: int,
    ) -> tuple[list[NewsWebMessage], bool]:
        calls.append((start, end, message_title, timeout))
        responses = {
            (date(2026, 7, 1), date(2026, 7, 3)): ([], True),
            (date(2026, 7, 1), date(2026, 7, 2)): ([july_2, july_1], False),
            (date(2026, 7, 3), date(2026, 7, 3)): ([july_3], False),
        }
        return responses[(start, end)]

    monkeypatch.setattr(client, "_list_window", fake_list_window)

    messages = client.discover_otec_messages(
        "2026-07-01",
        "2026-07-03",
        message_title="buyback",
        timeout=7,
    )

    assert [message.message_id for message in messages] == [101, 102, 103]
    assert calls == [
        (date(2026, 7, 1), date(2026, 7, 3), "buyback", 7),
        (date(2026, 7, 1), date(2026, 7, 2), "buyback", 7),
        (date(2026, 7, 3), date(2026, 7, 3), "buyback", 7),
    ]


def test_overflow_paa_enkelt_dato_stoppe_i_stedet_for_ufullstendig_resultat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nest viktigst: en dag som fortsatt er full må feile tydelig."""

    def fake_list_window(
        start: date,
        end: date,
        *,
        message_title: str,
        timeout: int,
    ) -> tuple[list[NewsWebMessage], bool]:
        return [_message(201, "2026-07-01T08:00:00Z")], True

    monkeypatch.setattr(client, "_list_window", fake_list_window)

    with pytest.raises(ValueError, match="overflow på enkelt dato 2026-07-01"):
        client.discover_otec_messages("2026-07-01", "2026-07-01")


def test_duplikater_fjernes_og_korrigert_melding_utelates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tredje viktigst: gjentatte og erstattede børsmeldinger skal ikke dobbelttelles."""
    original = _message(
        301,
        "2026-07-01T08:00:00Z",
        corrected_by_message_id=302,
        title="Opprinnelig melding",
    )
    correction = _message(
        302,
        "2026-07-01T09:00:00Z",
        title="Korrigert melding",
    )
    duplicate = _message(
        302,
        "2026-07-01T09:00:00Z",
        title="Korrigert melding fra overlappende svar",
    )

    def fake_discover_window(
        start: date,
        end: date,
        *,
        message_title: str,
        timeout: int,
    ) -> list[NewsWebMessage]:
        return [correction, original, duplicate]

    monkeypatch.setattr(client, "_discover_window", fake_discover_window)

    messages = client.discover_otec_messages("2026-07-01", "2026-07-02")

    assert len(messages) == 1
    assert messages[0].message_id == 302
    assert messages[0].title == "Korrigert melding fra overlappende svar"

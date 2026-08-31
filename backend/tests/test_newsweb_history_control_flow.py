"""Risikobaserte tester av kontrollflyten i NewsWeb-historikkjobben."""

from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.newsweb import history
from app.newsweb.client import NewsWebMessage


def _message(message_id: int, published_at: str) -> NewsWebMessage:
    return NewsWebMessage(
        message_id=message_id,
        news_id=message_id + 1_000,
        title=f"Otello-melding {message_id}",
        body=f"Meldingstekst {message_id}",
        issuer_id=7759,
        issuer_sign="OTEC",
        issuer_name="Otello Corporation ASA",
        published_at=published_at,
        markets=("XOSL",),
        category_ids=(1007,),
        attachments=(),
        corrected_by_message_id=0,
        correction_for_message_id=0,
        client_announcement_id=None,
    )


def test_timeout_for_en_melding_stopper_ikke_resten_av_arkiveringen(
    tmp_path, monkeypatch
) -> None:
    """Viktigst: én treg API-respons skal ikke koste hele historikkoppdateringen."""
    database = str(tmp_path / "delvis-historikk.db")
    init_database(database)
    messages = [
        _message(101, "2026-08-01T08:00:00Z"),
        _message(102, "2026-08-02T08:00:00Z"),
        _message(103, "2026-08-03T08:00:00Z"),
    ]
    fetch_calls: list[tuple[int, int]] = []

    def fake_discover(start: str, end: str, *, timeout: int) -> list[NewsWebMessage]:
        assert (start, end, timeout) == ("2026-08-01", "2026-08-03", 7)
        return messages

    def fake_fetch(message_id: int, *, timeout: int) -> NewsWebMessage:
        fetch_calls.append((message_id, timeout))
        if message_id == 102:
            raise TimeoutError("NewsWeb svarte ikke innen fristen")
        return next(item for item in messages if item.message_id == message_id)

    monkeypatch.setattr(history, "discover_otec_messages", fake_discover)
    monkeypatch.setattr(history, "fetch_message", fake_fetch)

    result = history.collect_newsweb_history(
        database,
        from_date="2026-08-01",
        to_date="2026-08-03",
        timeout=7,
    )

    assert fetch_calls == [(101, 7), (102, 7), (103, 7)]
    assert result["discovered"] == 3
    assert result["archived"] == 2
    assert result["errors"] == [
        {
            "message_id": 102,
            "published_at": "2026-08-02T08:00:00Z",
            "title": "Otello-melding 102",
            "error": "NewsWeb svarte ikke innen fristen",
        }
    ]


def test_nytt_forsoek_etter_delvis_feil_lagrer_meldingen_uten_duplikat(
    tmp_path, monkeypatch
) -> None:
    """Nest viktigst: en midlertidig feil må kunne repareres trygt ved neste kjøring."""
    database = str(tmp_path / "nytt-forsoek.db")
    init_database(database)
    message = _message(201, "2026-08-04T08:00:00Z")
    attempts = 0

    monkeypatch.setattr(
        history,
        "discover_otec_messages",
        lambda *_args, **_kwargs: [message],
    )

    def flaky_fetch(_message_id: int, *, timeout: int) -> NewsWebMessage:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TimeoutError("midlertidig timeout")
        return message

    monkeypatch.setattr(history, "fetch_message", flaky_fetch)

    first = history.collect_newsweb_history(
        database, from_date="2026-08-04", to_date="2026-08-04"
    )
    second = history.collect_newsweb_history(
        database, from_date="2026-08-04", to_date="2026-08-04"
    )

    assert first["archived"] == 0
    assert len(first["errors"]) == 1
    assert second["archived"] == 1
    assert second["errors"] == []
    with get_connection(database) as connection:
        count = connection.execute("""
            SELECT COUNT(*) AS count
            FROM source_documents
            WHERE external_id='newsweb-message:201'
            """).fetchone()["count"]
    assert count == 1


def test_tomt_api_svar_gir_tydelig_nullresultat_uten_databaseinnhold(
    tmp_path, monkeypatch
) -> None:
    """Tredje viktigst: ingen meldinger er et gyldig resultat, ikke en skjult feil."""
    database = str(tmp_path / "tom-historikk.db")
    init_database(database)
    monkeypatch.setattr(
        history,
        "discover_otec_messages",
        lambda *_args, **_kwargs: [],
    )

    result = history.collect_newsweb_history(
        database, from_date="2026-08-05", to_date="2026-08-05"
    )

    assert result == {
        "from": "2026-08-05",
        "to": "2026-08-05",
        "discovered": 0,
        "archived": 0,
        "errors": [],
        "requires_review": 0,
        "categories": {},
    }
    assert history.newsweb_history_status(database) == {"status": "empty", "count": 0}

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


def test_standardoppdatering_prover_eldre_feilet_melding_paa_nytt(
    tmp_path, monkeypatch
) -> None:
    """En gammel timeout må ikke falle ut når nyere meldinger flytter startdatoen."""
    database = str(tmp_path / "beholdt-nytt-forsoek.db")
    init_database(database)
    old_message = _message(301, "2026-01-02T08:00:00Z")
    new_message = _message(302, "2026-08-20T08:00:00Z")
    discovery_starts: list[str] = []
    old_attempts = 0

    def fake_discover(start: str, _end: str, **_kwargs) -> list[NewsWebMessage]:
        discovery_starts.append(start)
        return [old_message, new_message] if start <= "2026-01-02" else [new_message]

    def fake_fetch(message_id: int, **_kwargs) -> NewsWebMessage:
        nonlocal old_attempts
        if message_id == old_message.message_id:
            old_attempts += 1
            if old_attempts == 1:
                raise TimeoutError("midlertidig timeout")
            return old_message
        return new_message

    monkeypatch.setattr(history, "discover_otec_messages", fake_discover)
    monkeypatch.setattr(history, "fetch_message", fake_fetch)

    first = history.collect_newsweb_history(database, to_date="2026-08-31")
    second = history.collect_newsweb_history(database, to_date="2026-08-31")

    assert first["archived"] == 1
    assert len(first["errors"]) == 1
    assert discovery_starts == ["2020-01-01", "2026-01-02"]
    assert second["archived"] == 2
    assert second["errors"] == []
    assert old_attempts == 2


def test_retrydato_flyttes_frem_nar_gammel_feil_er_reparert(
    tmp_path, monkeypatch
) -> None:
    """En reparert gammel feil skal ikke holde historikkvinduet kunstig langt."""
    database = str(tmp_path / "flyttet-retrydato.db")
    init_database(database)
    old_message = _message(401, "2026-01-02T08:00:00Z")
    new_message = _message(402, "2026-08-20T08:00:00Z")
    run_number = 0

    monkeypatch.setattr(
        history,
        "discover_otec_messages",
        lambda *_args, **_kwargs: [old_message, new_message],
    )

    def alternating_failures(message_id: int, **_kwargs) -> NewsWebMessage:
        if run_number == 1 and message_id == old_message.message_id:
            raise TimeoutError("gammel midlertidig timeout")
        if run_number == 2 and message_id == new_message.message_id:
            raise TimeoutError("nyere midlertidig timeout")
        return old_message if message_id == old_message.message_id else new_message

    monkeypatch.setattr(history, "fetch_message", alternating_failures)

    run_number = 1
    first = history.collect_newsweb_history(database, to_date="2026-08-31")
    assert first["errors"][0]["message_id"] == old_message.message_id
    assert history.history_start_for_refresh(database) == "2026-01-02"

    run_number = 2
    second = history.collect_newsweb_history(database, to_date="2026-08-31")
    assert second["errors"][0]["message_id"] == new_message.message_id
    with get_connection(database) as connection:
        retry_from = connection.execute(
            "SELECT value FROM runtime_state WHERE key=?",
            (history.RETRY_FROM_STATE_KEY,),
        ).fetchone()["value"]
    assert retry_from == "2026-08-20"
    assert history.history_start_for_refresh(database) == "2026-08-06"


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

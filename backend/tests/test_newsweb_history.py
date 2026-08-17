import json

from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.newsweb.client import NewsWebAttachment, NewsWebMessage
from app.newsweb.history import (
    classify_newsweb_message,
    collect_newsweb_history,
    history_start_for_refresh,
    newsweb_history_status,
)


def _message(message_id: int, title: str, *, published: str = "2021-02-26T08:00:00Z") -> NewsWebMessage:
    return NewsWebMessage(
        message_id=message_id,
        news_id=message_id + 1000,
        title=title,
        body=f"Sensitive full body for {message_id}; it must only be hashed.",
        issuer_id=7759,
        issuer_sign="OTEC",
        issuer_name="Otello Corporation ASA",
        published_at=published,
        markets=("XOSL",),
        category_ids=(1007,),
        attachments=(NewsWebAttachment(message_id + 10, "source.pdf"),),
        corrected_by_message_id=0,
        correction_for_message_id=0,
        client_announcement_id=f"client-{message_id}",
    )


def test_newsweb_history_classifier_is_conservative() -> None:
    assert classify_newsweb_message(
        _message(1, "Otello Announces Definitive Agreement to sell AdColony to Digital Turbine")
    )[0] == "M_AND_A"
    assert classify_newsweb_message(_message(2, "Registration of share capital reduction"))[0] == "CAPITAL"
    assert classify_newsweb_message(
        _message(3, "Key information relating to cash dividend to be paid by Otello Corporation ASA")
    )[0] == "DIVIDEND"
    assert classify_newsweb_message(_message(4, "Otello Corporation share buyback program status"))[0] == "BUYBACK"
    assert classify_newsweb_message(_message(5, "Mandatory notification of trade"))[0] == "CORPORATE"

    category, review, _ = classify_newsweb_message(_message(6, "Transaction notification"))
    assert category == "OTHER"
    assert review is True


def test_full_newsweb_archive_is_idempotent_and_does_not_persist_body(tmp_path, monkeypatch) -> None:
    db = str(tmp_path / "history.db")
    init_database(db)
    messages = [
        _message(495017, "Registration of share capital reduction", published="2020-02-11T09:00:00Z"),
        _message(551454, "AdColony payment", published="2022-01-17T07:00:00Z"),
        _message(999999, "Unclassified historical notice", published="2023-01-02T07:00:00Z"),
    ]
    monkeypatch.setattr("app.newsweb.history.discover_otec_messages", lambda *args, **kwargs: messages)
    monkeypatch.setattr(
        "app.newsweb.history.fetch_message",
        lambda message_id, **kwargs: next(item for item in messages if item.message_id == message_id),
    )

    first = collect_newsweb_history(db, from_date="2020-01-01", to_date="2023-01-02")
    second = collect_newsweb_history(db, from_date="2020-01-01", to_date="2023-01-02")
    assert first["discovered"] == first["archived"] == 3
    assert second["archived"] == 3
    assert first["errors"] == []

    with get_connection(db) as connection:
        rows = connection.execute(
            """
            SELECT sd.external_id, sd.content_sha256, sd.metadata_json,
                   cn.issuer_instrument_id, cn.category, cn.processing_status,
                   cn.nav_impact, cn.summary, cn.notes
            FROM source_documents sd
            JOIN sources s ON s.id=sd.source_id
            JOIN company_news cn ON cn.source_document_id=sd.id
            WHERE s.code='NEWSWEB' AND sd.external_id LIKE 'newsweb-message:%'
            ORDER BY sd.external_id
            """
        ).fetchall()
        assert len(rows) == 3
        assert all(row["content_sha256"] for row in rows)
        assert all(row["issuer_instrument_id"] for row in rows)
        assert all(row["summary"] is None for row in rows)
        assert all("Sensitive full body" not in (row["notes"] or "") for row in rows)
        metadata = [json.loads(row["metadata_json"]) for row in rows]
        assert all(item["body_persisted"] is False for item in metadata)
        assert all("body" not in item for item in metadata)
        assert any(
            row["category"] == "OTHER" and row["processing_status"] == "REVIEW_REQUIRED"
            for row in rows
        )
        assert any(row["nav_impact"] == "POTENTIAL" for row in rows)

    status = newsweb_history_status(db)
    assert status["count"] == 3
    assert status["from"] == "2020-02-11"
    assert status["to"] == "2023-01-02"
    assert status["requires_review"] == 1
    assert status["by_year"] == {"2020": 1, "2022": 1, "2023": 1}


def test_incremental_history_refresh_overlaps_latest_date(tmp_path, monkeypatch) -> None:
    db = str(tmp_path / "incremental.db")
    init_database(db)
    message = _message(1, "Annual Report 2024", published="2025-04-30T08:00:00Z")
    monkeypatch.setattr("app.newsweb.history.discover_otec_messages", lambda *args, **kwargs: [message])
    monkeypatch.setattr("app.newsweb.history.fetch_message", lambda *args, **kwargs: message)
    collect_newsweb_history(db, from_date="2025-04-30", to_date="2025-04-30")
    assert history_start_for_refresh(db) == "2025-04-16"

from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
CLOUDFLARE_SRC = ROOT / "cloudflare" / "src"
for path in (str(BACKEND), str(CLOUDFLARE_SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from app.newsweb.weekly_parser import parse_newsweb_weekly_status as parse_reference_status  # noqa: E402
from newsweb_buybacks import (  # noqa: E402
    buyback_start_for_refresh,
    ingest_weekly_buyback,
    parse_newsweb_weekly_status,
)
from newsweb_client import (  # noqa: E402
    MAX_JSON_BYTES,
    NewsWebAttachment,
    NewsWebMessage,
    discover_otec_messages,
    fetch_message,
)
from newsweb_ingestion import classify_newsweb_message, history_start_for_refresh  # noqa: E402
from newsweb_daily_buybacks import parse_buyback_transaction_text as parse_worker_transaction_text  # noqa: E402

FIRST_WEEK_2023 = """
Reference is made to the stock exchange notices from 20 June 2023 announcing the initiation
of the share buyback program for Otello Corporation ASA (the Company). From 20 June 2023
through 23 June 2023, Pareto Securities AS has bought 99,087 shares on the behalf of the
Company at an average price of NOK 8.49 and a total value of NOK 841,269. The maximum
consideration to be paid for shares acquired under the buyback program is NOK 15 per share
and the maximum number of shares that can be purchased under this buyback program is
4 554 986 shares (5% of total outstanding shares).
"""

TYPO_WEEK_2023 = """
Reference is made to the stock exchange notices from 20 June 2023 announcing the initiation
of the share buyback program for Otello Corporation ASA (the Company). From 26 June 2023
through 30 June 2023, Pareto Securities AS has bought 182,642 shares on the behalf of the
Company at an average price of NOK 8.03 and a total value of NOK 1,466,062. Sine the
initiation of the share buyback program a total of 281,729 shares at an average price of NOK
8.19 and a total value of NOK 2,307,331 have been acquired. The maximum consideration to
be paid for shares acquired under the buyback program is NOK 15 per share and the maximum
number of shares that can be purchased under this buyback program is 4,554,986 shares.
At present date, Otello owns 281,729 treasury shares in the Company.
"""

LEGACY_WEEK_2024 = (
    "Reference is made to the stock exchange notice from 22 July 2024 announcing a share buyback program "
    "for Otello Corporation ASA (the Company). From 22 July 2024 through 26 July 2024, Pareto Securities AS "
    "has bought 56,000 shares on behalf of the Company at an average price of NOK 7.90 and a total value of "
    "NOK 442,353. Since the initiation of the share buyback program a total of 56,000 shares at an average "
    "price of NOK 7.90 and a total value of NOK 442,353 have been acquired. The maximum consideration to be "
    "paid for shares acquired under the buyback program is NOK 15 per share and the maximum number of shares "
    "that can be purchased is 4,554,986 shares (5% of total outstanding shares). At present date, Otello owns "
    "3,744,364 treasury shares in the Company."
)

CONTINUATION_WEEK_2025 = (
    "Reference is made to the stock exchange notice from 3 February 2025 announcing "
    "the continuation of the share buyback program for Otello Corporation ASA (the Company). "
    "From 10 February 2025 through 14 February 2025, Pareto Securities AS has bought "
    "346,900 shares on behalf of the Company at an average price of NOK 7.58 and a total value "
    "of NOK 2,631,058. Since the initiation of this continuation of the share buyback program "
    "a total of 649,900 shares at an average price of NOK 7.59 and a total value of NOK 4,933,848 "
    "have been acquired. The maximum consideration to be paid for shares acquired under this "
    "buyback program is NOK 15 per share and the maximum number of shares that can be purchased "
    "under this continuation of the buyback program is 866,690 shares (being the maximum remaining "
    "number of outstanding shares that can be purchased under the existing authorization). At "
    "present date, Otello owns 8,893,160 treasury shares in the Company."
)

DECIMAL_COMMA_WEEK_2025 = (
    "Reference is made to the stock exchange notice from 16 June 2025 announcing the initiation of the share "
    "buyback program for Otello Corporation ASA (the Company). From 14 July 2025 through 18 July 2025, Pareto "
    "Securities AS has bought 662,600 shares on behalf of the Company at an average price of NOK 13,17 and a "
    "total value of NOK 8,725,420. Since the initiation of this share buyback program a total of 2,828,800 shares "
    "at an average price of NOK 12.49 and a total value of NOK 35,320,824 have been acquired. The maximum number "
    "of shares that can be purchased under this buyback program is 5,047,130. At present date, Otello owns "
    "5,980,620 treasury shares in the Company."
)


def _message(
    message_id: int,
    title: str,
    *,
    body: str = "body",
    published: str = "2026-08-17T08:00:00Z",
    corrected_by: int = 0,
) -> NewsWebMessage:
    return NewsWebMessage(
        message_id=message_id,
        news_id=message_id + 1000,
        title=title,
        body=body,
        issuer_id=7759,
        issuer_sign="OTEC",
        issuer_name="Otello Corporation ASA",
        published_at=published,
        markets=("XOSL",),
        category_ids=(1007,),
        attachments=(NewsWebAttachment(message_id + 10, "source.pdf"),),
        corrected_by_message_id=corrected_by,
        correction_for_message_id=0,
        client_announcement_id=f"client-{message_id}",
    )


def _raw_message(message: NewsWebMessage, *, include_body: bool) -> dict:
    raw = {
        "messageId": message.message_id,
        "newsId": message.news_id,
        "title": message.title,
        "issuerId": message.issuer_id,
        "issuerSign": message.issuer_sign,
        "issuerName": message.issuer_name,
        "publishedTime": message.published_at,
        "markets": list(message.markets),
        "category": [{"id": value} for value in message.category_ids],
        "correctedByMessageId": message.corrected_by_message_id,
        "correctionForMessageId": message.correction_for_message_id,
        "clientAnnouncementId": message.client_announcement_id,
    }
    if include_body:
        raw["body"] = message.body
        raw["attachments"] = [
            {"id": item.attachment_id, "name": item.name} for item in message.attachments
        ]
    return raw


def _api_payload(data: dict) -> str:
    return json.dumps(
        {
            "header": {"result.val": 0, "http.code": 200},
            "data": data,
        }
    )


class FakeResponse:
    def __init__(self, text: str, *, content_length: int | None = None) -> None:
        self._text = text
        self.ok = True
        self.status = 200
        length = len(text.encode("utf-8")) if content_length is None else content_length
        self.headers = {"content-length": str(length)}
        self.text_called = False

    async def text(self):
        self.text_called = True
        return self._text


class ScalarRepository:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = list(rows)
        self.queries: list[str] = []

    async def first(self, sql: str, parameters=()):
        self.queries.append(sql)
        return self.rows.pop(0) if self.rows else None


class SqliteD1Repository:
    """Small async adapter that exercises the actual D1 schema with SQLite semantics."""

    def __init__(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        for migration in sorted((ROOT / "cloudflare" / "migrations").glob("*.sql")):
            self.connection.executescript(migration.read_text(encoding="utf-8"))
        self.connection.commit()

    async def run(self, sql: str, parameters=()):
        cursor = self.connection.execute(sql, parameters)
        self.connection.commit()
        return cursor

    async def all(self, sql: str, parameters=()):
        return [dict(row) for row in self.connection.execute(sql, parameters).fetchall()]

    async def first(self, sql: str, parameters=()):
        row = self.connection.execute(sql, parameters).fetchone()
        return dict(row) if row is not None else None

    async def source_id(self, code: str) -> int:
        row = await self.first("SELECT id FROM sources WHERE code=?", (code,))
        if row is None:
            raise ValueError(code)
        return int(row["id"])

    async def instrument_id(self, symbol: str) -> int:
        row = await self.first("SELECT id FROM instruments WHERE symbol=?", (symbol,))
        if row is None:
            raise ValueError(symbol)
        return int(row["id"])

    async def create_source_document(
        self,
        *,
        source_code: str,
        document_type: str,
        title: str,
        url: str,
        external_id: str | None = None,
        published_at: str | None = None,
        content_sha256: str | None = None,
        metadata: dict | None = None,
    ) -> int:
        source_id = await self.source_id(source_code)
        metadata_json = json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True)
        if external_id is not None:
            existing = await self.first(
                "SELECT id FROM source_documents WHERE source_id=? AND external_id=? LIMIT 1",
                (source_id, external_id),
            )
            if existing is not None:
                await self.run(
                    """
                    UPDATE source_documents
                    SET document_type=?, title=?, url=?, published_at=?, content_sha256=?, metadata_json=?
                    WHERE id=?
                    """,
                    (
                        document_type,
                        title,
                        url,
                        published_at,
                        content_sha256,
                        metadata_json,
                        int(existing["id"]),
                    ),
                )
                return int(existing["id"])
        cursor = await self.run(
            """
            INSERT INTO source_documents(
                source_id, external_id, document_type, title, published_at, url,
                content_sha256, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_id,
                external_id,
                document_type,
                title,
                published_at,
                url,
                content_sha256,
                metadata_json,
            ),
        )
        return int(cursor.lastrowid)


def test_worker_weekly_parser_matches_reference_for_documented_variants() -> None:
    for body in (
        FIRST_WEEK_2023,
        TYPO_WEEK_2023,
        LEGACY_WEEK_2024,
        CONTINUATION_WEEK_2025,
        DECIMAL_COMMA_WEEK_2025,
    ):
        worker = parse_newsweb_weekly_status(body)
        reference = parse_reference_status(body)
        assert asdict(worker) == asdict(reference)


def test_newsweb_worker_classifier_matches_conservative_reference_examples() -> None:
    assert classify_newsweb_message(
        _message(1, "Otello Announces Definitive Agreement to sell AdColony to Digital Turbine")
    )[0] == "M_AND_A"
    assert classify_newsweb_message(_message(2, "Registration of share capital reduction"))[0] == "CAPITAL"
    assert classify_newsweb_message(
        _message(3, "Key information relating to cash dividend to be paid by Otello Corporation ASA")
    )[0] == "DIVIDEND"
    assert classify_newsweb_message(_message(4, "Otello Corporation share buyback program status"))[0] == "BUYBACK"
    category, review, _ = classify_newsweb_message(_message(5, "Transaction notification"))
    assert category == "OTHER"
    assert review is True


def test_incremental_overlap_windows_match_reference_policy() -> None:
    history_repo = ScalarRepository([{"latest_date": "2025-04-30"}])
    assert asyncio.run(history_start_for_refresh(history_repo)) == "2025-04-16"

    buyback_repo = ScalarRepository([{"latest_date": "2026-08-14"}])
    assert asyncio.run(buyback_start_for_refresh(buyback_repo)) == "2026-07-24"


def test_newsweb_client_recurses_on_overflow_and_drops_superseded_messages() -> None:
    current = _message(101, "Annual Report 2026", published="2026-08-04T08:00:00Z")
    corrected = _message(
        100,
        "Annual Report 2026 - old",
        published="2026-08-03T08:00:00Z",
        corrected_by=101,
    )
    calls: list[tuple[str, str]] = []

    async def fake_fetch(url: str, **kwargs):
        assert kwargs["method"] == "POST"
        assert kwargs["body"] == "{}"
        assert "Connection" not in kwargs["headers"]
        query = parse_qs(urlparse(url).query)
        start = query["fromDate"][0]
        end = query["toDate"][0]
        calls.append((start, end))
        if (start, end) == ("2026-08-01", "2026-08-04"):
            return FakeResponse(_api_payload({"messages": [], "overflow": True}))
        if (start, end) == ("2026-08-01", "2026-08-02"):
            return FakeResponse(_api_payload({"messages": [], "overflow": False}))
        if (start, end) == ("2026-08-03", "2026-08-04"):
            return FakeResponse(
                _api_payload(
                    {
                        "messages": [
                            _raw_message(corrected, include_body=False),
                            _raw_message(current, include_body=False),
                        ],
                        "overflow": False,
                    }
                )
            )
        raise AssertionError((start, end))

    messages = asyncio.run(
        discover_otec_messages("2026-08-01", "2026-08-04", fetcher=fake_fetch)
    )

    assert [item.message_id for item in messages] == [101]
    assert calls == [
        ("2026-08-01", "2026-08-04"),
        ("2026-08-01", "2026-08-02"),
        ("2026-08-03", "2026-08-04"),
    ]


def test_newsweb_client_rejects_oversized_json_before_reading_body() -> None:
    response = FakeResponse("{}", content_length=MAX_JSON_BYTES + 1)

    async def fake_fetch(url: str, **kwargs):
        return response

    with pytest.raises(ValueError, match="overstiger Worker-grensen"):
        asyncio.run(fetch_message(678028, fetcher=fake_fetch))
    assert response.text_called is False


def test_worker_weekly_buyback_writes_actual_d1_schema_idempotently() -> None:
    repository = SqliteD1Repository()
    try:
        newsweb_source = asyncio.run(repository.source_id("NEWSWEB"))
        seed_document = repository.connection.execute(
            """
            INSERT INTO source_documents(
                source_id, external_id, document_type, title, url, metadata_json
            ) VALUES (?, 'seed-share-count', 'REGULATORY_NEWS', 'Seed share count',
                      'https://example.test/seed', '{}')
            """,
            (newsweb_source,),
        ).lastrowid
        repository.connection.execute(
            """
            INSERT INTO otello_share_counts(
                effective_from, total_shares, treasury_shares, outstanding_shares,
                source_document_id, notes
            ) VALUES ('2025-06-01', 100000000, 0, 100000000, ?, 'test anchor')
            """,
            (seed_document,),
        )
        repository.connection.commit()

        parsed = parse_newsweb_weekly_status(DECIMAL_COMMA_WEEK_2025)
        message = _message(
            678028,
            "Otello Corporation share buyback program status",
            body=DECIMAL_COMMA_WEEK_2025,
            published="2025-07-18T16:00:00Z",
        )

        first = asyncio.run(ingest_weekly_buyback(repository, message, parsed))
        second = asyncio.run(ingest_weekly_buyback(repository, message, parsed))

        assert first["period_end"] == second["period_end"] == "2025-07-18"
        assert first["period_shares"] == 662_600
        assert first["period_amount_nok"] == "8725420"
        assert first["treasury_shares_after"] == 5_980_620
        assert first["outstanding_shares_after"] == 94_019_380
        assert first["attachment_status"] == "DEFERRED_TO_FULL_REFRESH_R2"

        counts = {
            "programs": repository.connection.execute(
                "SELECT COUNT(*) FROM buyback_programs"
            ).fetchone()[0],
            "weeks": repository.connection.execute(
                "SELECT COUNT(*) FROM buybacks"
            ).fetchone()[0],
            "weekly_cash": repository.connection.execute(
                "SELECT COUNT(*) FROM cash_movements WHERE movement_type='OTELLO_BUYBACK'"
            ).fetchone()[0],
            "weekly_share_counts": repository.connection.execute(
                "SELECT COUNT(*) FROM otello_share_counts WHERE effective_from='2025-07-18'"
            ).fetchone()[0],
        }
        assert counts == {
            "programs": 1,
            "weeks": 1,
            "weekly_cash": 1,
            "weekly_share_counts": 1,
        }

        buyback = repository.connection.execute(
            """
            SELECT shares, avg_price_nok, amount_nok, cumulative_program_shares,
                   treasury_shares_after
            FROM buybacks
            """
        ).fetchone()
        assert dict(buyback) == {
            "shares": 662_600,
            "avg_price_nok": "13.17",
            "amount_nok": "8725420",
            "cumulative_program_shares": 2_828_800,
            "treasury_shares_after": 5_980_620,
        }

        cash = repository.connection.execute(
            """
            SELECT movement_date, amount_nok, confidence
            FROM cash_movements WHERE movement_type='OTELLO_BUYBACK'
            """
        ).fetchone()
        assert dict(cash) == {
            "movement_date": "2025-07-18",
            "amount_nok": "-8725420",
            "confidence": "CONFIRMED",
        }
    finally:
        repository.connection.close()


def test_worker_newsweb_does_not_overwrite_stronger_euronext_buyback_fact() -> None:
    repository = SqliteD1Repository()
    try:
        newsweb_source = asyncio.run(repository.source_id("NEWSWEB"))
        euronext_source = asyncio.run(repository.source_id("EURONEXT"))
        seed_document = repository.connection.execute(
            """
            INSERT INTO source_documents(source_id, external_id, document_type, title, url, metadata_json)
            VALUES (?, 'seed-share-count-stronger', 'REGULATORY_NEWS', 'Seed', 'https://example.test/seed', '{}')
            """,
            (newsweb_source,),
        ).lastrowid
        repository.connection.execute(
            """
            INSERT INTO otello_share_counts(
                effective_from,total_shares,treasury_shares,outstanding_shares,source_document_id,notes
            ) VALUES ('2025-06-01',100000000,0,100000000,?,'test anchor')
            """,
            (seed_document,),
        )
        strong_document = repository.connection.execute(
            """
            INSERT INTO source_documents(source_id, external_id, document_type, title, url, metadata_json)
            VALUES (?, 'strong-euronext-week', 'REGULATORY_NEWS', 'Strong', 'https://example.test/strong', '{}')
            """,
            (euronext_source,),
        ).lastrowid
        program_id = repository.connection.execute(
            """
            INSERT INTO buyback_programs(
                external_program_id, announced_at, start_date, max_shares, status, source_document_id
            ) VALUES ('otec-buyback-2025-06-16','2025-06-16T00:00:00Z','2025-06-16',5047130,'ACTIVE',?)
            """,
            (strong_document,),
        ).lastrowid
        repository.connection.execute(
            """
            INSERT INTO buybacks(
                program_id, period_start, trade_date, shares, avg_price_nok, amount_nok,
                cumulative_program_shares, cumulative_program_avg_price_nok,
                cumulative_program_amount_nok, treasury_shares_after, source_document_id
            ) VALUES (?, '2025-07-14','2025-07-18',662601,'13.17','8725420',
                      2828800,'12.49','35320824',5980620,?)
            """,
            (program_id, strong_document),
        )
        repository.connection.commit()

        parsed = parse_newsweb_weekly_status(DECIMAL_COMMA_WEEK_2025)
        message = _message(
            678029,
            "Otello Corporation share buyback program status",
            body=DECIMAL_COMMA_WEEK_2025,
            published="2025-07-18T16:00:00Z",
        )
        with pytest.raises(ValueError, match="sterkere fakta"):
            asyncio.run(ingest_weekly_buyback(repository, message, parsed))

        shares = repository.connection.execute(
            "SELECT shares FROM buybacks WHERE program_id=? AND trade_date='2025-07-18'",
            (program_id,),
        ).fetchone()[0]
        assert shares == 662_601
    finally:
        repository.connection.close()



def test_worker_recovers_680519_duplicate_time_date_defect_fail_closed() -> None:
    text = """
B OTEC 13 000 17,00 221 000,00 10:00:00 17.08.2026
ExecBuy 13 000
B OTEC 13 000 17,00 221 000,00 10:00:00 18.08.2026
ExecBuy 13 000
B OTEC 12 000 17,00 204 000,00 10:00:00 19.08.2026
ExecBuy 12 000
B OTEC 13 000 17,00 221 000,00 10:00:00 20.08.2026
ExecBuy 13 000
B OTEC 8 000 17,00 136 000,00 10:42:30 10:42:30
B OTEC 5 000 17,00 85 000,00 10:14:00 10:14:00
ExecBuy 13 000
"""
    rows = parse_worker_transaction_text(
        text, period_start="2026-08-17", period_end="2026-08-21"
    )
    assert [row.trade_date for row in rows][-1] == "2026-08-21"
    assert [row.shares for row in rows] == [13_000, 13_000, 12_000, 13_000, 13_000]

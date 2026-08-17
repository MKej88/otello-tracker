from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.history.newsweb_2021_events import seed_2021_newsweb_events


def _seed_usd_fx(db: str, rate: str = "8.50") -> None:
    with get_connection(db) as connection:
        source_id = connection.execute("SELECT id FROM sources WHERE code='ECB'").fetchone()["id"]
        connection.execute(
            """
            INSERT INTO fx_rates(base_currency, quote_currency, observed_at, rate, source_id)
            VALUES ('USD','NOK','2021-10-27T16:00:00Z',?,?)
            """,
            (rate, source_id),
        )
        connection.commit()


def test_2021_newsweb_events_seed_exact_tenders_cash_and_share_counts(tmp_path) -> None:
    db = str(tmp_path / "events-2021.db")
    init_database(db)
    _seed_usd_fx(db)

    first = seed_2021_newsweb_events(db)
    second = seed_2021_newsweb_events(db)
    assert len(first["buybacks"]) == 3
    assert len(second["buybacks"]) == 3
    assert first["missing_fx"] == []

    with get_connection(db) as connection:
        buybacks = connection.execute(
            """
            SELECT trade_date, shares, avg_price_nok, amount_nok, treasury_shares_after
            FROM buybacks WHERE trade_date LIKE '2021-%' ORDER BY trade_date
            """
        ).fetchall()
        assert [(r["trade_date"], r["shares"], r["amount_nok"]) for r in buybacks] == [
            ("2021-05-10", 12_000_000, "405000000.00"),
            ("2021-09-06", 12_450_000, "410850000.00"),
            ("2021-12-08", 11_200_000, "296800000.00"),
        ]
        assert [r["treasury_shares_after"] for r in buybacks] == [13_727_702, 12_450_000, 11_200_000]

        cash = connection.execute(
            """
            SELECT movement_date, movement_type, amount_nok, amount_original, currency, confidence
            FROM cash_movements ORDER BY movement_date, id
            """
        ).fetchall()
        assert [(r["movement_date"], r["movement_type"], r["amount_nok"]) for r in cash] == [
            ("2021-05-10", "OTELLO_BUYBACK", "-405000000.00"),
            ("2021-09-06", "OTELLO_BUYBACK", "-410850000.00"),
            ("2021-10-27", "OTHER", "850000000.00"),
            ("2021-12-08", "OTELLO_BUYBACK", "-296800000.00"),
        ]
        adcolony = cash[2]
        assert adcolony["amount_original"] == "100000000"
        assert adcolony["currency"] == "USD"
        assert adcolony["confidence"] == "CONFIRMED"

        share_counts = connection.execute(
            """
            SELECT effective_from, total_shares, treasury_shares, outstanding_shares
            FROM otello_share_counts WHERE effective_from IN ('2021-09-06','2021-11-24','2021-12-08')
            ORDER BY effective_from
            """
        ).fetchall()
        assert [tuple(r) for r in share_counts] == [
            ("2021-09-06", 124_749_727, 12_450_000, 112_299_727),
            ("2021-11-24", 112_299_727, 0, 112_299_727),
            ("2021-12-08", 112_299_727, 11_200_000, 101_099_727),
        ]

        assert connection.execute(
            "SELECT COUNT(*) n FROM buybacks WHERE trade_date LIKE '2021-%'"
        ).fetchone()["n"] == 3
        assert connection.execute(
            "SELECT COUNT(*) n FROM cash_movements WHERE movement_date LIKE '2021-%'"
        ).fetchone()["n"] == 4
        assert connection.execute(
            """
            SELECT COUNT(*) n FROM otello_share_counts
            WHERE effective_from IN ('2021-09-06','2021-11-24','2021-12-08')
            """
        ).fetchone()["n"] == 3


def test_2021_newsweb_static_events_survive_missing_fx(tmp_path) -> None:
    db = str(tmp_path / "events-2021-no-fx.db")
    init_database(db)
    result = seed_2021_newsweb_events(db)
    assert result["adcolony_payment"] is None
    assert result["missing_fx"] == [{"movement_date": "2021-10-27", "currency": "USD"}]
    with get_connection(db) as connection:
        assert connection.execute("SELECT COUNT(*) n FROM buybacks").fetchone()["n"] == 3
        assert connection.execute(
            "SELECT COUNT(*) n FROM cash_movements WHERE movement_type='OTELLO_BUYBACK'"
        ).fetchone()["n"] == 3
        assert connection.execute(
            "SELECT COUNT(*) n FROM otello_share_counts WHERE effective_from LIKE '2021-%'"
        ).fetchone()["n"] == 3


def test_report_anchor_can_supersede_december_event_share_count(tmp_path) -> None:
    db = str(tmp_path / "events-2021-anchor.db")
    init_database(db)
    seed_2021_newsweb_events(db)
    with get_connection(db) as connection:
        # Reuse a NewsWeb source document as a foreign-key-safe source for this isolated lookup test.
        document_id = connection.execute(
            "SELECT id FROM source_documents ORDER BY id LIMIT 1"
        ).fetchone()["id"]
        connection.execute(
            """
            INSERT INTO otello_share_counts(
                effective_from,total_shares,treasury_shares,outstanding_shares,source_document_id,notes
            ) VALUES ('2021-12-31',112299727,11199998,101099729,?,'report anchor test')
            """,
            (document_id,),
        )
        latest = connection.execute(
            """
            SELECT outstanding_shares FROM otello_share_counts
            WHERE effective_from <= '2021-12-31'
            ORDER BY effective_from DESC, id DESC LIMIT 1
            """
        ).fetchone()
        assert latest["outstanding_shares"] == 101_099_729
        connection.commit()

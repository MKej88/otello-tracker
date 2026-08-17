from decimal import Decimal

from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.history import seed_curated_history
from app.history.distributions import seed_bemobi_distributions
from app.nav.cash_curve import sync_corporate_action_cash_movements


def _source_id(connection, code: str) -> int:
    return int(connection.execute("SELECT id FROM sources WHERE code = ?", (code,)).fetchone()["id"])


def _insert_brl_nok(connection, day: str, rate: str = "2") -> None:
    connection.execute(
        """
        INSERT OR REPLACE INTO fx_rates(base_currency, quote_currency, observed_at, rate, source_id)
        VALUES ('BRL', 'NOK', ?, ?, ?)
        """,
        (f"{day}T16:00:00Z", rate, _source_id(connection, "ECB")),
    )


def test_bemobi_distribution_manifest_is_component_level_and_idempotent(tmp_path) -> None:
    database = str(tmp_path / "bemobi.db")
    init_database(database)
    seed_curated_history(database)

    first = seed_bemobi_distributions(database)
    second = seed_bemobi_distributions(database)
    assert first["count"] == 12
    assert second["count"] == 12

    with get_connection(database) as connection:
        total = connection.execute(
            """
            SELECT COUNT(*) AS n
            FROM corporate_actions ca
            JOIN instruments i ON i.id = ca.issuer_instrument_id
            WHERE i.symbol = 'BMOB3' AND ca.external_action_id IS NOT NULL
            """
        ).fetchone()["n"]
        assert total == 12

        mixed_2024 = connection.execute(
            """
            SELECT action_type, gross_total_amount, component_group
            FROM corporate_actions
            WHERE payment_date = '2025-01-07' AND component_group = 'bemobi-2024-12-11-mixed'
            ORDER BY action_type
            """
        ).fetchall()
        assert len(mixed_2024) == 2
        assert {row["action_type"] for row in mixed_2024} == {"DIVIDEND", "JCP"}
        assert sum(Decimal(row["gross_total_amount"]) for row in mixed_2024) == Decimal("55000000.00")

        mixed_2025 = connection.execute(
            """
            SELECT action_type, gross_total_amount, gross_amount_per_share
            FROM corporate_actions
            WHERE payment_date = '2025-12-22' AND component_group = 'bemobi-2025-12-08-mixed'
            ORDER BY id
            """
        ).fetchall()
        assert len(mixed_2025) == 3
        assert [row["action_type"] for row in mixed_2025].count("JCP") == 1
        assert [row["action_type"] for row in mixed_2025].count("DIVIDEND") == 2
        assert sum(Decimal(row["gross_total_amount"]) for row in mixed_2025) == Decimal("134217363.44")
        assert sum(Decimal(row["gross_amount_per_share"]) for row in mixed_2025) == Decimal("1.590555")

        jcp_2026_may = connection.execute(
            """
            SELECT action_type, gross_amount_per_share, net_amount_per_share,
                   withholding_rate, tax_treatment
            FROM corporate_actions
            WHERE external_action_id = 'bemobi-2026-05-27-jcp'
            """
        ).fetchone()
        assert jcp_2026_may["action_type"] == "JCP"
        assert Decimal(jcp_2026_may["gross_amount_per_share"]) == Decimal("0.18818727094")
        assert Decimal(jcp_2026_may["net_amount_per_share"]) == Decimal("0.15525449853")
        assert Decimal(jcp_2026_may["withholding_rate"]) == Decimal("0.175")
        assert jcp_2026_may["tax_treatment"] == "PUBLISHED_NET"

        jcp_2026_aug = connection.execute(
            """
            SELECT ca.action_type, ca.announcement_date, ca.record_date, ca.ex_date,
                   ca.payment_date, ca.gross_amount_per_share, ca.net_amount_per_share,
                   ca.gross_total_amount, ca.net_total_amount, ca.withholding_rate,
                   ca.tax_treatment, ca.notes, s.code AS source_code
            FROM corporate_actions ca
            JOIN source_documents sd ON sd.id = ca.source_document_id
            JOIN sources s ON s.id = sd.source_id
            WHERE ca.external_action_id = 'bemobi-2026-08-28-jcp-2q26'
            """
        ).fetchone()
        assert jcp_2026_aug["action_type"] == "JCP"
        assert jcp_2026_aug["announcement_date"] == "2026-08-11"
        assert jcp_2026_aug["record_date"] == "2026-08-14"
        assert jcp_2026_aug["ex_date"] == "2026-08-17"
        assert jcp_2026_aug["payment_date"] == "2026-08-28"
        assert Decimal(jcp_2026_aug["gross_amount_per_share"]) == Decimal("0.19178292")
        assert Decimal(jcp_2026_aug["net_amount_per_share"]) == Decimal("0.15822091")
        assert Decimal(jcp_2026_aug["gross_total_amount"]) == Decimal("16000000.00")
        assert Decimal(jcp_2026_aug["net_total_amount"]) == Decimal("13200000.00")
        assert Decimal(jcp_2026_aug["withholding_rate"]) == Decimal("0.175")
        assert jcp_2026_aug["tax_treatment"] == "PUBLISHED_NET"
        assert jcp_2026_aug["source_code"] == "CVM"
        assert "83,427,657" in jcp_2026_aug["notes"]
        assert "may change" in jcp_2026_aug["notes"]
        assert "ESTIMATED_GROSS" in jcp_2026_aug["notes"]


def test_jcp_withholding_is_separate_cash_tax_and_reconciles_to_published_net(tmp_path) -> None:
    database = str(tmp_path / "bemobi-tax.db")
    init_database(database)
    seed_curated_history(database)

    with get_connection(database) as connection:
        for day in ("2024-05-02", "2025-01-07", "2025-12-22", "2026-05-27"):
            _insert_brl_nok(connection, day)
        connection.commit()

    sync_corporate_action_cash_movements(database)

    with get_connection(database) as connection:
        adjustments = connection.execute(
            """
            SELECT COUNT(*) AS n FROM cash_movements
            WHERE external_movement_id LIKE 'bemobi-withholding:%'
            """
        ).fetchone()["n"]
        # August 2026 is not booked yet because this test deliberately has no payment-date FX.
        assert adjustments == 4

        action = connection.execute(
            """
            SELECT id FROM corporate_actions
            WHERE external_action_id = 'bemobi-2026-05-27-jcp'
            """
        ).fetchone()
        gross = connection.execute(
            """
            SELECT amount_original, amount_nok, confidence
            FROM cash_movements WHERE corporate_action_id = ?
            """,
            (action["id"],),
        ).fetchone()
        tax = connection.execute(
            """
            SELECT amount_original, amount_nok, confidence, description
            FROM cash_movements
            WHERE external_movement_id = 'bemobi-withholding:bemobi-2026-05-27-jcp'
            """
        ).fetchone()

        assert Decimal(gross["amount_original"]) == Decimal("6157409.97200117272")
        assert Decimal(tax["amount_original"]) == Decimal("-1077546.74495296708")
        assert Decimal(gross["amount_original"]) + Decimal(tax["amount_original"]) == Decimal("5079863.22704820564")
        assert Decimal(gross["amount_nok"]) + Decimal(tax["amount_nok"]) == Decimal("10159726.45409641128")
        assert gross["confidence"] == "ESTIMATED"
        assert tax["confidence"] == "ESTIMATED"
        assert "PUBLISHED_NET" in tax["description"]

        standard = connection.execute(
            """
            SELECT description FROM cash_movements
            WHERE external_movement_id = 'bemobi-withholding:bemobi-2025-12-22-jcp'
            """
        ).fetchone()
        assert "STANDARD_WITHHOLDING" in standard["description"]

        unknown = connection.execute(
            """
            SELECT COUNT(*) AS n FROM cash_movements
            WHERE external_movement_id = 'bemobi-withholding:bemobi-2025-12-01-jcp'
            """
        ).fetchone()["n"]
        assert unknown == 0


def test_august_2026_jcp_books_gross_and_tax_when_payment_fx_exists(tmp_path) -> None:
    database = str(tmp_path / "bemobi-august-tax.db")
    init_database(database)
    seed_curated_history(database)

    with get_connection(database) as connection:
        _insert_brl_nok(connection, "2026-08-28", "2")
        connection.commit()

    sync_corporate_action_cash_movements(database)

    with get_connection(database) as connection:
        action = connection.execute(
            """
            SELECT id FROM corporate_actions
            WHERE external_action_id = 'bemobi-2026-08-28-jcp-2q26'
            """
        ).fetchone()
        gross = connection.execute(
            """
            SELECT movement_date, movement_type, amount_original, amount_nok, confidence
            FROM cash_movements WHERE corporate_action_id = ?
            """,
            (action["id"],),
        ).fetchone()
        tax = connection.execute(
            """
            SELECT movement_date, movement_type, amount_original, amount_nok,
                   confidence, description
            FROM cash_movements
            WHERE external_movement_id = 'bemobi-withholding:bemobi-2026-08-28-jcp-2q26'
            """
        ).fetchone()

        assert gross["movement_date"] == "2026-08-28"
        assert gross["movement_type"] == "BEMOBI_JCP"
        assert Decimal(gross["amount_original"]) == Decimal("6275058.12783696")
        assert Decimal(gross["amount_nok"]) == Decimal("12550116.25567392")
        assert tax["movement_date"] == "2026-08-28"
        assert tax["movement_type"] == "TAX"
        assert Decimal(tax["amount_original"]) == Decimal("-1098135.13965188")
        assert Decimal(tax["amount_nok"]) == Decimal("-2196270.27930376")
        assert Decimal(gross["amount_original"]) + Decimal(tax["amount_original"]) == Decimal("5176922.98818508")
        assert Decimal(gross["amount_nok"]) + Decimal(tax["amount_nok"]) == Decimal("10353845.97637016")
        assert gross["confidence"] == "ESTIMATED"
        assert tax["confidence"] == "ESTIMATED"
        assert "PUBLISHED_NET" in tax["description"]


def test_existing_withholding_is_not_deleted_by_temporary_fx_gap(tmp_path) -> None:
    database = str(tmp_path / "bemobi-tax-gap.db")
    init_database(database)
    seed_curated_history(database)

    with get_connection(database) as connection:
        for day in ("2024-05-02", "2025-01-07", "2025-12-22", "2026-05-27"):
            _insert_brl_nok(connection, day)
        connection.commit()

    seed_bemobi_distributions(database)
    with get_connection(database) as connection:
        before = {
            row["external_movement_id"]: row["amount_nok"]
            for row in connection.execute(
                """
                SELECT external_movement_id, amount_nok FROM cash_movements
                WHERE external_movement_id LIKE 'bemobi-withholding:%'
                ORDER BY external_movement_id
                """
            ).fetchall()
        }
        assert len(before) == 4
        connection.execute("DELETE FROM fx_rates WHERE base_currency = 'BRL' AND quote_currency = 'NOK'")
        connection.commit()

    result = seed_bemobi_distributions(database)
    assert result["withholding_adjustments"]["deleted"] == 0

    with get_connection(database) as connection:
        after = {
            row["external_movement_id"]: row["amount_nok"]
            for row in connection.execute(
                """
                SELECT external_movement_id, amount_nok FROM cash_movements
                WHERE external_movement_id LIKE 'bemobi-withholding:%'
                ORDER BY external_movement_id
                """
            ).fetchall()
        }
        assert after == before

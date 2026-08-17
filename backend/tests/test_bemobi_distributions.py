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
    assert first["count"] == 11
    assert second["count"] == 11

    with get_connection(database) as connection:
        total = connection.execute(
            """
            SELECT COUNT(*) AS n
            FROM corporate_actions ca
            JOIN instruments i ON i.id = ca.issuer_instrument_id
            WHERE i.symbol = 'BMOB3' AND ca.external_action_id IS NOT NULL
            """
        ).fetchone()["n"]
        assert total == 11

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

        jcp_2026 = connection.execute(
            """
            SELECT action_type, gross_amount_per_share, net_amount_per_share,
                   withholding_rate, tax_treatment
            FROM corporate_actions
            WHERE external_action_id = 'bemobi-2026-05-27-jcp'
            """
        ).fetchone()
        assert jcp_2026["action_type"] == "JCP"
        assert Decimal(jcp_2026["gross_amount_per_share"]) == Decimal("0.18818727094")
        assert Decimal(jcp_2026["net_amount_per_share"]) == Decimal("0.15525449853")
        assert Decimal(jcp_2026["withholding_rate"]) == Decimal("0.175")
        assert jcp_2026["tax_treatment"] == "PUBLISHED_NET"


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

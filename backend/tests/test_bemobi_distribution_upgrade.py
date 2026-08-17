from app.db.connection import get_connection
from app.db.migration_runner import init_database
from app.db.repository import create_source_document, instrument_id
from app.history import seed_curated_history
from app.history.distributions import seed_bemobi_distributions


def test_legacy_mixed_distribution_is_upgraded_without_duplicate(tmp_path) -> None:
    database = str(tmp_path / "legacy-bemobi.db")
    init_database(database)
    seed_curated_history(database)

    with get_connection(database) as connection:
        old_document_id = create_source_document(
            connection,
            source_code="BEMOBI_IR",
            external_id="bemobi-dividend-history-2024",
            document_type="IR_PAGE",
            title="Legacy Bemobi dividend history - 2024 distribution",
            url="https://ri.bemobi.com.br/nossas-acoes/dividendos/",
        )
        issuer_id = instrument_id(connection, "BMOB3")
        cursor = connection.execute(
            """
            INSERT INTO corporate_actions(
                issuer_instrument_id, action_type, ex_date, payment_date,
                amount_per_share, total_amount, currency, source_document_id, notes
            ) VALUES (?, 'DIVIDEND', '2024-12-18', '2025-01-07',
                      '0.64384496', '55000000.00', 'BRL', ?, 'legacy aggregate')
            """,
            (issuer_id, old_document_id),
        )
        legacy_id = int(cursor.lastrowid)
        connection.commit()

    seed_bemobi_distributions(database)
    seed_bemobi_distributions(database)

    with get_connection(database) as connection:
        rows = connection.execute(
            """
            SELECT id, action_type, external_action_id, component_group,
                   gross_total_amount, source_document_id
            FROM corporate_actions ca
            JOIN instruments i ON i.id = ca.issuer_instrument_id
            WHERE i.symbol = 'BMOB3'
              AND ca.ex_date = '2024-12-18' AND ca.payment_date = '2025-01-07'
            ORDER BY ca.id
            """
        ).fetchall()

        assert len(rows) == 2
        assert {row["action_type"] for row in rows} == {"DIVIDEND", "JCP"}
        assert {row["external_action_id"] for row in rows} == {
            "bemobi-2025-01-07-dividend-2024",
            "bemobi-2025-01-07-jcp-2024",
        }
        assert {row["component_group"] for row in rows} == {"bemobi-2024-12-11-mixed"}
        assert legacy_id in {int(row["id"]) for row in rows}
        assert all(row["source_document_id"] != old_document_id for row in rows)

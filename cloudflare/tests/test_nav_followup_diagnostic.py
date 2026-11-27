from __future__ import annotations

import sqlite3
import unittest

from nav_followup_diagnostic import assess_followup, followup_queries, render_followup


class FollowupTests(unittest.TestCase):
    def test_readonly_queries_and_redaction(self):
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.executescript("""
        CREATE TABLE estimated_nav_history_retry_queue(date, calculation_version, reason,
            attempts, first_failed_at, last_failed_at, next_retry_at);
        INSERT INTO estimated_nav_history_retry_queue VALUES
          ('2025-01-01','ESTIMATED_NAV_V1','missing_option_inputs',3,'2026-01-01','2026-01-02','2026-01-03'),
          ('2025-01-02','ESTIMATED_NAV_V1','secret=private-value',1,'2026-01-01','2026-01-02','9999-01-01'),
          ('2025-01-03','OTHER','missing_option_inputs',1,'2026-01-01','2026-01-02','2026-01-03');
        CREATE TABLE other_net_assets_daily_estimates(estimate_date, receivable_quality,
            associated_receivable_nok, receivable_components_json);
        CREATE TABLE nav_snapshots(id, as_of_at, nav_scope, calculation_version);
        CREATE TABLE corporate_actions(id, action_type, ex_date, payment_date, amount_per_share,
            net_amount_per_share, withholding_rate, tax_treatment, source_document_id);
        INSERT INTO nav_snapshots VALUES(1,'2026-11-27T23:59:59Z','FULL','full-market-nav-daily-v2');
        INSERT INTO other_net_assets_daily_estimates VALUES('2026-11-27','ESTIMATED_GROSS','40',
            '[{"corporate_action_id":20,"holding_shares":100,"brl_nok":"2","amount_nok":"40"}]');
        INSERT INTO corporate_actions VALUES(20,'JCP','2026-11-18','2026-11-30',
            '0.20','0.165','0.175','PUBLISHED_NET',88);
        """)
        rows = [[dict(r) for r in db.execute(q["sql"], q["params"])] for q in followup_queries()]
        report = assess_followup(*rows, preflight={"warnings": []})
        self.assertEqual(report["pending"], 2)
        self.assertEqual(report["due"], 1)
        self.assertTrue(report["warning"])
        rendered = render_followup(report)
        self.assertIn("missing_option_inputs", rendered)
        self.assertIn("2025-01-01", rendered)
        self.assertIn("OTHER", rendered)
        self.assertNotIn("private-value", rendered)
        self.assertIn("33.00 NOK", rendered)
        self.assertIn("7.00 NOK", rendered)

    def test_healthy_and_unconfirmed_are_distinguished(self):
        self.assertFalse(assess_followup([], [], [{"receivable_quality": "NONE"}],
                                        preflight={})["warning"])
        self.assertTrue(assess_followup([], [], [], preflight={})["warning"])
        self.assertTrue(assess_followup([], [], [{"receivable_quality": "NONE"}],
                                       preflight={"warnings": [{}]})["warning"])

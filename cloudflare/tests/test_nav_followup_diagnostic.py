from __future__ import annotations

import sqlite3
import unittest

from nav_followup_diagnostic import assess_followup, followup_queries, render_followup, cost_anchor_query


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


    def test_net_estimate_and_pre_anchor_backlog(self):
        anchors = [{"scenario": "BASE", "effective_from": "2023-06-30",
                    "amount_usd": "1673000", "period_days": 181},
                   {"scenario": "BASE", "effective_from": "2022-01-01",
                    "amount_usd": "-1", "period_days": 181}]
        net = [{"receivable_quality": "ESTIMATED_NET", "estimate_date": "2026-11-27"}]
        healthy = assess_followup([], [], net, preflight={}, cost_anchors=anchors)
        self.assertFalse(healthy["warning"])
        self.assertIn("ESTIMATED_NET", render_followup(healthy))
        self.assertNotIn("UKJENT", render_followup(healthy))
        groups = [{"reason_code": "missing_estimated_nav_anchor", "count": 250,
                   "due": 30, "last_date": "2023-06-29"}]
        report = assess_followup(groups, [], net, preflight={}, cost_anchors=anchors)
        self.assertFalse(report["warning"])
        self.assertEqual(report["first_base_anchor"], "2023-06-30")
        self.assertEqual(report["before_base_anchor"], 250)
        self.assertEqual(report["pending"], 0)
        self.assertEqual(report["due"], 0)
        self.assertEqual(report["total_pending"], 250)
        earlier = [{"scenario": "BASE", "effective_from": "2022-07-01",
                    "amount_usd": "1000", "period_days": 181}]
        mixed = [{"reason_code": "missing_estimated_nav_anchor", "count": 2,
                  "due": 2, "last_date": "2023-07-01",
                  "coverage_dates": '[["2022-07-01",1],["2023-07-01",1]]'}]
        partial = assess_followup(mixed, [], net, preflight={}, cost_anchors=anchors)
        self.assertEqual(partial["pending"], 1)
        self.assertEqual(partial["due"], 1)
        self.assertTrue(partial["warning"])
        reopened = assess_followup(mixed, [], net, preflight={}, cost_anchors=earlier)
        self.assertEqual(reopened["pending"], 2)
        self.assertEqual(reopened["before_base_anchor"], 0)
        self.assertTrue(reopened["warning"])
        db = sqlite3.connect(":memory:")
        db.executescript("""
        CREATE TABLE source_documents(id, published_at, document_type, metadata_json);
        INSERT INTO source_documents VALUES(1, '2023-06-30','ECONOMIC_NAV_COST_ANCHOR',
           '{"scenario":"BASE","effective_from":"2023-06-30","amount_usd":"1673000","period_days":181}');
        INSERT INTO source_documents VALUES(2, '2023-01-01','ECONOMIC_NAV_COST_ANCHOR','not json');
        """)
        self.assertEqual(db.execute(cost_anchor_query()["sql"]).fetchall(),
                         [(1, "BASE", "2023-06-30", "1673000", 181)])

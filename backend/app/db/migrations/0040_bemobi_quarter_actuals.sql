-- Historical comparison columns in Table 3, page 3, BTG report 08.10.2026.
-- Stored independently: do not rewrite TTM, valuation, RESULT or BEAT_MISS facts.
CREATE TABLE IF NOT EXISTS bemobi_quarter_actuals (
    period TEXT PRIMARY KEY,
    period_end TEXT NOT NULL,
    published_date TEXT NOT NULL,
    source_name TEXT NOT NULL,
    source_url TEXT NOT NULL,
    source_page INTEGER,
    source_evidence TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

INSERT INTO bemobi_quarter_actuals(
    period, period_end, published_date, source_name, source_url,
    source_page, source_evidence, metrics_json, notes
) VALUES
    ('3Q25', '2025-09-30', '2026-10-08', 'BTG Pactual', 'https://content.btgpactual.com/research/files/file/pt-BR/2026-10-08T104612.283_Telecom___Tech___Pr_vias_de_TMT___Parte_II__Intelbras__Totvs__Bemobi_e_LWSA_.pdf',
     3, 'PDF_TABLE_VERIFIED', '[{"metric":"revenue_mbrl","label":"Omsetning (netto)","value_mbrl":187.5},{"metric":"adjusted_ebitda_mbrl","label":"Justert EBITDA","value_mbrl":62.7},{"metric":"adjusted_net_income_mbrl","label":"Justert nettoresultat","value_mbrl":42.5},{"metric":"ebitda_margin_pct","label":"Justert EBITDA-margin","value_pct":33.4},{"metric":"payments_revenue_mbrl","label":"Omsetning – Payments","value_mbrl":73.8},{"metric":"saas_revenue_mbrl","label":"Omsetning – SaaS","value_mbrl":39.7},{"metric":"subscriptions_revenue_mbrl","label":"Omsetning – Subscriptions","value_mbrl":53.0},{"metric":"microfinance_revenue_mbrl","label":"Omsetning – Microfinance","value_mbrl":20.9},{"metric":"capex_mbrl","label":"Capex","value_mbrl":15.2},{"metric":"capex_to_sales_pct","label":"Capex / omsetning","value_pct":8.1},{"metric":"operating_free_cash_flow_mbrl","label":"Operasjonell fri kontantstrøm (OpFCF)","value_mbrl":47.4}]',
     'Rapporterte sammenligningstall fra BTGs tabell 3, kolonne 3Q25. Nettoomsetning og justert nettoresultat følger denne tabellens definisjoner; øvrige historiske beregninger er uendret.'),
    ('2Q26', '2026-06-30', '2026-10-08', 'BTG Pactual', 'https://content.btgpactual.com/research/files/file/pt-BR/2026-10-08T104612.283_Telecom___Tech___Pr_vias_de_TMT___Parte_II__Intelbras__Totvs__Bemobi_e_LWSA_.pdf',
     3, 'PDF_TABLE_VERIFIED', '[{"metric":"revenue_mbrl","label":"Omsetning (netto)","value_mbrl":227.3},{"metric":"adjusted_ebitda_mbrl","label":"Justert EBITDA","value_mbrl":79.4},{"metric":"adjusted_net_income_mbrl","label":"Justert nettoresultat","value_mbrl":45.2},{"metric":"ebitda_margin_pct","label":"Justert EBITDA-margin","value_pct":34.9},{"metric":"payments_revenue_mbrl","label":"Omsetning – Payments","value_mbrl":112.0},{"metric":"saas_revenue_mbrl","label":"Omsetning – SaaS","value_mbrl":46.1},{"metric":"subscriptions_revenue_mbrl","label":"Omsetning – Subscriptions","value_mbrl":48.7},{"metric":"microfinance_revenue_mbrl","label":"Omsetning – Microfinance","value_mbrl":20.5},{"metric":"capex_mbrl","label":"Capex","value_mbrl":14.7},{"metric":"capex_to_sales_pct","label":"Capex / omsetning","value_pct":6.5},{"metric":"operating_free_cash_flow_mbrl","label":"Operasjonell fri kontantstrøm (OpFCF)","value_mbrl":64.8}]',
     'Rapporterte sammenligningstall fra BTGs tabell 3, kolonne 2Q26. Nettoomsetning og justert nettoresultat følger denne tabellens definisjoner; øvrige historiske beregninger er uendret.')
ON CONFLICT(period) DO NOTHING;

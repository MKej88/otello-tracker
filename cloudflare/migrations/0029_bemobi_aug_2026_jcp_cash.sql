-- Seed the official 2Q26 Bemobi JCP and materialize its already-passed payment.
-- Future confirmed BMOB3 DIVIDEND/JCP actions are handled generically by
-- bemobi_distribution_sync.py; this migration repairs production immediately.

INSERT OR IGNORE INTO source_documents(
    source_id, external_id, document_type, title, published_at, url, metadata_json
)
SELECT
    s.id,
    'bemobi-jcp-notice-2026-aug-cvm-1556263-v2',
    'SHAREHOLDER_NOTICE',
    'Bemobi notice to shareholders - August 2026 JCP 2Q26',
    '2026-08-12',
    'https://www.rad.cvm.gov.br/ENET/frmDownloadDocumento.aspx?Tela=ext&descTipo=IPE&CodigoInstituicao=1&numProtocolo=1556263&numSequencia=1080969&numVersao=2',
    '{"curated":true,"source":"CVM","purpose":"Bemobi 2Q26 JCP entitlement and payment lifecycle"}'
FROM sources s
WHERE s.code='CVM';

INSERT OR IGNORE INTO corporate_actions(
    issuer_instrument_id, action_type, announcement_date, ex_date,
    record_date, payment_date, amount_per_share, total_amount,
    currency, source_document_id, notes, external_action_id,
    gross_amount_per_share, net_amount_per_share, gross_total_amount,
    net_total_amount, withholding_rate, tax_treatment, component_group
)
SELECT
    i.id,
    'JCP',
    '2026-08-11',
    '2026-08-17',
    '2026-08-14',
    '2026-08-28',
    '0.19178292',
    '16000000.00',
    'BRL',
    sd.id,
    'Official CVM shareholder notice. Gross entitlement is a receivable from ex-date through 2026-08-27; on 2026-08-28 it becomes net cash after the published 17.5% withholding.',
    'bemobi-2026-08-28-jcp-2q26',
    '0.19178292',
    '0.15822091',
    '16000000.00',
    '13200000.00',
    '0.175',
    'PUBLISHED_NET',
    NULL
FROM instruments i
JOIN source_documents sd ON sd.external_id='bemobi-jcp-notice-2026-aug-cvm-1556263-v2'
JOIN sources s ON s.id=sd.source_id AND s.code='CVM'
WHERE i.symbol='BMOB3';

-- Repair an already-existing row as well; external_action_id is the stable identity.
UPDATE corporate_actions
SET action_type='JCP',
    announcement_date='2026-08-11',
    ex_date='2026-08-17',
    record_date='2026-08-14',
    payment_date='2026-08-28',
    amount_per_share='0.19178292',
    total_amount='16000000.00',
    currency='BRL',
    source_document_id=(
        SELECT sd.id
        FROM source_documents sd
        JOIN sources s ON s.id=sd.source_id
        WHERE s.code='CVM'
          AND sd.external_id='bemobi-jcp-notice-2026-aug-cvm-1556263-v2'
        LIMIT 1
    ),
    notes='Official CVM shareholder notice. Gross entitlement is a receivable from ex-date through 2026-08-27; on 2026-08-28 it becomes net cash after the published 17.5% withholding.',
    gross_amount_per_share='0.19178292',
    net_amount_per_share='0.15822091',
    gross_total_amount='16000000.00',
    net_total_amount='13200000.00',
    withholding_rate='0.175',
    tax_treatment='PUBLISHED_NET'
WHERE external_action_id='bemobi-2026-08-28-jcp-2q26';

-- The deployment itself should repair today's NAV instead of waiting for the next nightly
-- run. Use the latest BRL/NOK observation on or before the payment date (max 7-day lookback).
WITH payment AS (
    SELECT
        ca.id AS corporate_action_id,
        ca.source_document_id,
        ca.payment_date,
        ca.amount_per_share,
        ca.net_amount_per_share,
        h.shares,
        fr.rate
    FROM corporate_actions ca
    JOIN instruments i ON i.id=ca.issuer_instrument_id AND i.symbol='BMOB3'
    JOIN bemobi_holdings h
      ON h.effective_from <= ca.ex_date
     AND (h.effective_to IS NULL OR h.effective_to >= ca.ex_date)
    JOIN fx_rates fr ON fr.id=(
        SELECT fr2.id
        FROM fx_rates fr2
        JOIN sources s2 ON s2.id=fr2.source_id
        WHERE fr2.base_currency='BRL'
          AND fr2.quote_currency='NOK'
          AND substr(fr2.observed_at,1,10) <= ca.payment_date
          AND substr(fr2.observed_at,1,10) >= date(ca.payment_date, '-7 days')
        ORDER BY substr(fr2.observed_at,1,10) DESC,
                 CASE s2.code WHEN 'NORGES_BANK' THEN 0 WHEN 'ECB' THEN 1 ELSE 5 END,
                 fr2.observed_at DESC,
                 fr2.id DESC
        LIMIT 1
    )
    WHERE ca.external_action_id='bemobi-2026-08-28-jcp-2q26'
    ORDER BY h.effective_from DESC, h.id DESC
    LIMIT 1
)
INSERT OR IGNORE INTO cash_movements(
    movement_date, movement_type, amount_nok, amount_original,
    currency, fx_rate_to_nok, description, source_document_id,
    confidence, corporate_action_id
)
SELECT
    payment_date,
    'BEMOBI_JCP',
    printf('%.12f', CAST(amount_per_share AS REAL) * shares * CAST(rate AS REAL)),
    printf('%.12f', CAST(amount_per_share AS REAL) * shares),
    'BRL',
    rate,
    'Confirmed Bemobi JCP receipt from the official 2Q26 shareholder notice; gross receipt booked on the confirmed payment date and withholding stored separately.',
    source_document_id,
    'ESTIMATED',
    corporate_action_id
FROM payment;

WITH payment AS (
    SELECT
        ca.source_document_id,
        ca.payment_date,
        ca.amount_per_share,
        ca.net_amount_per_share,
        h.shares,
        fr.rate
    FROM corporate_actions ca
    JOIN instruments i ON i.id=ca.issuer_instrument_id AND i.symbol='BMOB3'
    JOIN bemobi_holdings h
      ON h.effective_from <= ca.ex_date
     AND (h.effective_to IS NULL OR h.effective_to >= ca.ex_date)
    JOIN fx_rates fr ON fr.id=(
        SELECT fr2.id
        FROM fx_rates fr2
        JOIN sources s2 ON s2.id=fr2.source_id
        WHERE fr2.base_currency='BRL'
          AND fr2.quote_currency='NOK'
          AND substr(fr2.observed_at,1,10) <= ca.payment_date
          AND substr(fr2.observed_at,1,10) >= date(ca.payment_date, '-7 days')
        ORDER BY substr(fr2.observed_at,1,10) DESC,
                 CASE s2.code WHEN 'NORGES_BANK' THEN 0 WHEN 'ECB' THEN 1 ELSE 5 END,
                 fr2.observed_at DESC,
                 fr2.id DESC
        LIMIT 1
    )
    WHERE ca.external_action_id='bemobi-2026-08-28-jcp-2q26'
    ORDER BY h.effective_from DESC, h.id DESC
    LIMIT 1
)
INSERT OR IGNORE INTO cash_movements(
    movement_date, movement_type, amount_nok, amount_original,
    currency, fx_rate_to_nok, description, source_document_id,
    confidence, external_movement_id
)
SELECT
    payment_date,
    'TAX',
    printf('%.12f', -(CAST(amount_per_share AS REAL) - CAST(net_amount_per_share AS REAL)) * shares * CAST(rate AS REAL)),
    printf('%.12f', -(CAST(amount_per_share AS REAL) - CAST(net_amount_per_share AS REAL)) * shares),
    'BRL',
    rate,
    'Bemobi JCP withholding adjustment from published gross/net amounts (17.5% notice rate).',
    source_document_id,
    'ESTIMATED',
    'bemobi-withholding:bemobi-2026-08-28-jcp-2q26'
FROM payment;

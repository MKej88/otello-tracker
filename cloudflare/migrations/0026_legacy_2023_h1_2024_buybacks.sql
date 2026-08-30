-- Production D1 backfill for the Otello buyback program initiated 20 June 2023.
-- Backend/bootstrap seeds the same canonical facts from the curated source modules.
-- This migration is gated on an existing production history anchor so a fresh empty D1
-- remains empty until the deterministic bootstrap fixture is imported.
--
-- Raw issuer weekly amounts and two stale treasury disclosures are retained in source
-- metadata. Model rows use the issuer's cumulative program totals as the control.

CREATE TEMP TABLE _otec_buyback_2023_h1_2024 (
    release_date TEXT NOT NULL,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL PRIMARY KEY,
    shares INTEGER NOT NULL,
    avg_price_nok TEXT NOT NULL,
    amount_nok TEXT NOT NULL,
    cumulative_shares INTEGER NOT NULL,
    cumulative_avg_price_nok TEXT NOT NULL,
    cumulative_amount_nok TEXT NOT NULL,
    url TEXT NOT NULL,
    raw_weekly_amount_nok TEXT NOT NULL,
    raw_treasury_shares INTEGER NOT NULL
);

INSERT INTO _otec_buyback_2023_h1_2024 VALUES
    ('2023-06-26', '2023-06-20', '2023-06-23', 99087, '8.49', '841269', 99087, '8.49', '841269', 'https://live.euronext.com/en/products/equities/company-news/2023-06-26-otello-corporation-share-buyback-program-status', '841269', 99087),
    ('2023-07-03', '2023-06-26', '2023-06-30', 182642, '8.03', '1466062', 281729, '8.19', '2307331', 'https://live.euronext.com/en/products/equities/company-news/2023-07-03-otello-corporation-share-buyback-program-status', '1466062', 281729),
    ('2023-07-10', '2023-07-03', '2023-07-07', 286627, '8.23', '2359638', 568356, '8.21', '4666969', 'https://live.euronext.com/en/products/equities/company-news/2023-07-10-otello-corporation-share-buyback-program-status', '2359639', 568356),
    ('2023-07-17', '2023-07-10', '2023-07-14', 446900, '8.64', '3861674', 1015256, '8.40', '8528643', 'https://live.euronext.com/en/products/equities/company-news/2023-07-17-otello-corporation-share-buyback-program-status', '3861673', 1015256),
    ('2023-07-24', '2023-07-17', '2023-07-21', 335247, '8.88', '2976591', 1350503, '8.52', '11505234', 'https://live.euronext.com/en/products/equities/company-news/2023-07-24-otello-corporation-share-buyback-program-status', '2976591', 1350503),
    ('2023-07-31', '2023-07-24', '2023-07-28', 407604, '9.34', '3805344', 1758107, '8.71', '15310578', 'https://live.euronext.com/en/products/equities/company-news/2023-07-31-otello-corporation-share-buyback-program-status', '3805344', 1758107),
    ('2023-08-07', '2023-07-31', '2023-08-04', 331443, '9.33', '3091448', 2089550, '8.81', '18402026', 'https://live.euronext.com/en/products/equities/company-news/2023-08-07-otello-corporation-share-buyback-program-status', '3091438', 2089550),
    ('2023-08-14', '2023-08-07', '2023-08-11', 134406, '9.21', '1237501', 2223956, '8.83', '19639527', 'https://live.euronext.com/en/products/equities/company-news/2023-08-14-otello-corporation-share-buyback-program-status', '1237510', 2223956),
    ('2023-08-21', '2023-08-14', '2023-08-18', 96349, '8.76', '843910', 2320305, '8.83', '20483437', 'https://live.euronext.com/en/products/equities/company-news/2023-08-21-otello-corporation-share-buyback-program-status', '843911', 2320305),
    ('2023-08-28', '2023-08-21', '2023-08-25', 68362, '8.46', '578280', 2388667, '8.82', '21061717', 'https://live.euronext.com/en/products/equities/company-news/2023-08-28-otello-corporation-share-buyback-program-status', '578280', 2388667),
    ('2023-09-04', '2023-08-28', '2023-09-01', 66055, '8.31', '549053', 2454722, '8.80', '21610770', 'https://live.euronext.com/en/products/equities/company-news/2023-09-04-otello-corporation-share-buyback-program-status', '549053', 2454722),
    ('2023-09-11', '2023-09-04', '2023-09-08', 51352, '8.33', '427894', 2506074, '8.79', '22038664', 'https://live.euronext.com/en/products/equities/company-news/2023-09-11-otello-corporation-share-buyback-program-status', '427894', 2506074),
    ('2023-09-18', '2023-09-11', '2023-09-15', 15957, '8.26', '131730', 2522031, '8.79', '22170394', 'https://live.euronext.com/en/products/equities/company-news/2023-09-18-otello-corporation-share-buyback-program-status', '131731', 2522031),
    ('2023-09-25', '2023-09-18', '2023-09-22', 32753, '8.19', '268176', 2554784, '8.78', '22438570', 'https://live.euronext.com/en/products/equities/company-news/2023-09-25-otello-corporation-share-buyback-program-status', '268176', 2554784),
    ('2023-10-02', '2023-09-25', '2023-09-29', 41769, '7.90', '329798', 2596553, '8.77', '22768368', 'https://live.euronext.com/en/products/equities/company-news/2023-10-02-otello-corporation-share-buyback-program-status', '329798', 2596553),
    ('2023-10-09', '2023-10-02', '2023-10-06', 41532, '7.77', '322576', 2638085, '8.75', '23090944', 'https://live.euronext.com/en/products/equities/company-news/2023-10-09-otello-corporation-share-buyback-program-status', '322576', 2638085),
    ('2023-10-16', '2023-10-09', '2023-10-13', 50832, '7.77', '394937', 2688917, '8.73', '23485881', 'https://live.euronext.com/en/products/equities/company-news/2023-10-16-otello-corporation-share-buyback-program-status', '394937', 2688917),
    ('2023-10-23', '2023-10-16', '2023-10-20', 55322, '7.71', '426469', 2744239, '8.71', '23912350', 'https://live.euronext.com/en/products/equities/company-news/2023-10-23-otello-corporation-share-buyback-program-status', '426469', 2744239),
    ('2023-10-30', '2023-10-23', '2023-10-27', 51279, '7.48', '383492', 2795518, '8.69', '24295842', 'https://live.euronext.com/en/products/equities/company-news/2023-10-30-otello-corporation-share-buyback-program-status', '383494', 2795518),
    ('2023-11-06', '2023-10-30', '2023-11-03', 63756, '7.49', '477452', 2859274, '8.66', '24773294', 'https://live.euronext.com/en/products/equities/company-news/2023-11-06-otello-corporation-share-buyback-program-status', '477451', 2859274),
    ('2023-11-13', '2023-11-06', '2023-11-10', 71155, '7.66', '545103', 2930429, '8.64', '25318397', 'https://live.euronext.com/en/products/equities/company-news/2023-11-13-otello-corporation-share-buyback-program-status', '545103', 2930429),
    ('2023-11-20', '2023-11-13', '2023-11-17', 70937, '7.91', '560860', 3001366, '8.62', '25879257', 'https://live.euronext.com/en/products/equities/company-news/2023-11-20-otello-corporation-share-buyback-program-status', '560860', 3001366),
    ('2023-11-27', '2023-11-20', '2023-11-24', 64923, '7.95', '516133', 3066289, '8.61', '26395390', 'https://live.euronext.com/en/products/equities/company-news/2023-11-27-otello-corporation-share-buyback-program-status', '516134', 3066289),
    ('2023-12-06', '2023-11-27', '2023-12-05', 36988, '7.71', '285272', 3103277, '8.60', '26680662', 'https://live.euronext.com/en/products/equities/company-news/2023-12-06-otello-corporation-share-buyback-program-status', '285271', 3103277),
    ('2023-12-11', '2023-12-06', '2023-12-08', 18048, '7.65', '138108', 3121325, '8.59', '26818770', 'https://live.euronext.com/en/products/equities/company-news/2023-12-11-otello-corporation-share-buyback-program-status', '138108', 3121325),
    ('2023-12-18', '2023-12-11', '2023-12-15', 26172, '7.96', '208336', 3147497, '8.59', '27027106', 'https://live.euronext.com/en/products/equities/company-news/2023-12-18-otello-corporation-share-buyback-program-status', '208336', 3147497),
    ('2023-12-27', '2023-12-18', '2023-12-22', 21221, '8.11', '172163', 3168718, '8.58', '27199269', 'https://live.euronext.com/en/products/equities/company-news/2023-12-27-otello-corporation-share-buyback-program-status', '172163', 3168718),
    ('2024-01-01', '2023-12-27', '2023-12-29', 11309, '8.10', '91629', 3180027, '8.58', '27290898', 'https://live.euronext.com/en/products/equities/company-news/2024-01-01-otello-corporation-share-buyback-program-status', '91630', 3180027),
    ('2024-01-07', '2024-01-02', '2024-01-05', 17527, '8.01', '140461', 3197554, '8.58', '27431359', 'https://live.euronext.com/en/products/equities/company-news/2024-01-07-otello-corporation-share-buyback-program-status', '140460', 3197554),
    ('2024-01-14', '2024-01-08', '2024-01-12', 31504, '7.98', '251511', 3229058, '8.57', '27682870', 'https://live.euronext.com/en/products/equities/company-news/2024-01-14-otello-corporation-share-buyback-program-status', '251512', 3229058),
    ('2024-01-21', '2024-01-16', '2024-01-19', 23573, '7.93', '186891', 3252631, '8.57', '27869761', 'https://live.euronext.com/en/products/equities/company-news/2024-01-21-otello-corporation-share-buyback-program-status', '186891', 3252631),
    ('2024-01-27', '2024-01-22', '2024-01-26', 9192, '7.87', '72338', 3261823, '8.57', '27942099', 'https://live.euronext.com/en/products/equities/company-news/2024-01-27-otello-corporation-share-buyback-program-status', '72338', 3261823),
    ('2024-02-03', '2024-01-29', '2024-02-01', 12004, '8.06', '96735', 3273827, '8.56', '28038834', 'https://live.euronext.com/en/products/equities/company-news/2024-02-03-otello-corporation-share-buyback-program-status', '96735', 3273827),
    ('2024-02-11', '2024-02-07', '2024-02-09', 4665, '7.79', '36323', 3278492, '8.56', '28075157', 'https://live.euronext.com/en/products/equities/company-news/2024-02-11-otello-corporation-share-buyback-program-status', '36322', 3273827),
    ('2024-02-17', '2024-02-12', '2024-02-16', 5041, '7.66', '38602', 3283533, '8.56', '28113759', 'https://live.euronext.com/en/products/equities/company-news/2024-02-17-otello-corporation-share-buyback-program-status', '38603', 3283533),
    ('2024-02-24', '2024-02-20', '2024-02-23', 7272, '7.75', '56359', 3290805, '8.56', '28170118', 'https://live.euronext.com/en/products/equities/company-news/2024-02-24-otello-corporation-share-buyback-program-status', '56358', 3290805),
    ('2024-03-03', '2024-02-26', '2024-03-01', 10007, '7.72', '77214', 3300812, '8.56', '28247332', 'https://live.euronext.com/en/products/equities/company-news/2024-03-03-otello-corporation-share-buyback-program-status', '77215', 3300812),
    ('2024-03-08', '2024-03-04', '2024-03-08', 9450, '7.74', '73178', 3310262, '8.56', '28320510', 'https://live.euronext.com/en/products/equities/company-news/2024-03-08-otello-corporation-share-buyback-program-status', '73178', 3310262),
    ('2024-03-16', '2024-03-12', '2024-03-15', 12421, '7.87', '97792', 3322683, '8.55', '28418302', 'https://live.euronext.com/en/products/equities/company-news/2024-03-16-otello-corporation-share-buyback-program-status', '97791', 3322683),
    ('2024-03-22', '2024-03-19', '2024-03-22', 10092, '7.80', '78735', 3332775, '8.55', '28497037', 'https://live.euronext.com/en/products/equities/company-news/2024-03-22-otello-corporation-share-buyback-program-status', '78735', 3322683),
    ('2024-03-27', '2024-03-25', '2024-03-27', 13000, '8.18', '106285', 3345775, '8.55', '28603322', 'https://live.euronext.com/en/products/equities/company-news/2024-03-27-otello-corporation-share-buyback-program-status', '106285', 3345775),
    ('2024-04-07', '2024-04-02', '2024-04-05', 24315, '8.29', '201665', 3370090, '8.55', '28804987', 'https://live.euronext.com/en/products/equities/company-news/2024-04-07-otello-corporation-share-buyback-program-status', '201665', 3370090),
    ('2024-04-14', '2024-04-08', '2024-04-12', 25290, '8.14', '205916', 3395380, '8.54', '29010903', 'https://live.euronext.com/en/products/equities/company-news/2024-04-14-otello-corporation-share-buyback-program-status', '205916', 3395380),
    ('2024-04-21', '2024-04-15', '2024-04-19', 36299, '8.12', '294577', 3431679, '8.54', '29305480', 'https://live.euronext.com/en/products/equities/company-news/2024-04-21-otello-corporation-share-buyback-program-status', '294577', 3431679),
    ('2024-04-28', '2024-04-22', '2024-04-26', 48799, '8.05', '392667', 3480478, '8.53', '29698147', 'https://live.euronext.com/en/products/equities/company-news/2024-04-28-otello-corporation-share-buyback-program-status', '392667', 3480478),
    ('2024-05-05', '2024-04-29', '2024-05-03', 34755, '7.83', '272111', 3515233, '8.53', '29970258', 'https://live.euronext.com/en/products/equities/company-news/2024-05-05-otello-corporation-share-buyback-program-status', '272110', 3515233),
    ('2024-05-12', '2024-05-06', '2024-05-10', 40727, '7.75', '315738', 3555960, '8.52', '30285996', 'https://live.euronext.com/en/products/equities/company-news/2024-05-12-otello-corporation-share-buyback-program-status', '315739', 3555960),
    ('2024-05-18', '2024-05-13', '2024-05-16', 45610, '7.72', '352178', 3601570, '8.51', '30638174', 'https://live.euronext.com/en/products/equities/company-news/2024-05-18-otello-corporation-share-buyback-program-status', '352177', 3601570),
    ('2024-05-24', '2024-05-21', '2024-05-23', 41320, '7.69', '317867', 3642890, '8.50', '30956041', 'https://live.euronext.com/en/products/equities/company-news/2024-05-24-otello-corporation-share-buyback-program-status', '317868', 3642890),
    ('2024-06-01', '2024-05-27', '2024-05-31', 45474, '7.72', '350965', 3688364, '8.49', '31307006', 'https://live.euronext.com/en/products/equities/company-news/2024-06-01-otello-corporation-share-buyback-program-status', '350965', 3688364);

INSERT INTO source_documents(
    source_id, external_id, document_type, title, published_at, url, content_sha256, metadata_json
)
SELECT s.id,
       t.url,
       'REGULATORY_NEWS_MIRROR',
       'Otello Corporation share buyback program status - curated official transcription',
       t.release_date || 'T00:00:00Z',
       t.url,
       NULL,
       '{"source_quality":"CURATED_OFFICIAL_TRANSCRIPTION","canonical_provider":"Euronext / Oslo Bors Newspoint","structured_transcription":true,"reconciliation":"CUMULATIVE_PROGRAM_CONTROL","raw_weekly_amount_nok":"' ||
       t.raw_weekly_amount_nok || '","raw_treasury_shares":' || CAST(t.raw_treasury_shares AS TEXT) || '}'
FROM _otec_buyback_2023_h1_2024 t
JOIN sources s ON s.code='MANUAL'
WHERE EXISTS (
    SELECT 1 FROM cash_anchors ca
    WHERE ca.as_of_date='2024-06-30' AND ca.anchor_type='REPORTED'
)
  AND NOT EXISTS (
      SELECT 1 FROM source_documents sd
      WHERE sd.source_id=s.id AND sd.external_id=t.url
  );

INSERT INTO buyback_programs(
    external_program_id, announced_at, start_date, end_date, max_shares,
    max_amount_nok, status, source_document_id, notes, max_price_nok
)
SELECT 'otec-buyback-2023-06-20',
       '2023-06-20T00:00:00Z',
       '2023-06-20',
       NULL,
       4554986,
       NULL,
       'ACTIVE',
       sd.id,
       'Program reconstructed from curated official Euronext/Oslo Bors weekly status releases; production backfill 0026.',
       NULL
FROM source_documents sd
JOIN sources s ON s.id=sd.source_id AND s.code='MANUAL'
WHERE sd.external_id=(
    SELECT url FROM _otec_buyback_2023_h1_2024 ORDER BY period_end LIMIT 1
)
  AND EXISTS (
      SELECT 1 FROM cash_anchors ca
      WHERE ca.as_of_date='2024-06-30' AND ca.anchor_type='REPORTED'
  )
  AND NOT EXISTS (
      SELECT 1 FROM buyback_programs p
      WHERE p.external_program_id='otec-buyback-2023-06-20'
  );

-- Reconcile any pre-existing partial row in place while retaining its stronger source,
-- then fill the missing logical weeks from the curated MANUAL source documents.
UPDATE buybacks
SET period_start = (
        SELECT t.period_start FROM _otec_buyback_2023_h1_2024 t
        WHERE t.period_end=buybacks.trade_date
    ),
    shares = (
        SELECT t.shares FROM _otec_buyback_2023_h1_2024 t
        WHERE t.period_end=buybacks.trade_date
    ),
    avg_price_nok = (
        SELECT t.avg_price_nok FROM _otec_buyback_2023_h1_2024 t
        WHERE t.period_end=buybacks.trade_date
    ),
    amount_nok = (
        SELECT t.amount_nok FROM _otec_buyback_2023_h1_2024 t
        WHERE t.period_end=buybacks.trade_date
    ),
    cumulative_program_shares = (
        SELECT t.cumulative_shares FROM _otec_buyback_2023_h1_2024 t
        WHERE t.period_end=buybacks.trade_date
    ),
    cumulative_program_avg_price_nok = (
        SELECT t.cumulative_avg_price_nok FROM _otec_buyback_2023_h1_2024 t
        WHERE t.period_end=buybacks.trade_date
    ),
    cumulative_program_amount_nok = (
        SELECT t.cumulative_amount_nok FROM _otec_buyback_2023_h1_2024 t
        WHERE t.period_end=buybacks.trade_date
    ),
    treasury_shares_after = (
        SELECT t.cumulative_shares FROM _otec_buyback_2023_h1_2024 t
        WHERE t.period_end=buybacks.trade_date
    )
WHERE program_id=(
        SELECT id FROM buyback_programs
        WHERE external_program_id='otec-buyback-2023-06-20'
    )
  AND EXISTS (
      SELECT 1 FROM _otec_buyback_2023_h1_2024 t
      WHERE t.period_end=buybacks.trade_date
  );

INSERT INTO buybacks(
    program_id, period_start, trade_date, shares, avg_price_nok, amount_nok,
    cumulative_program_shares, cumulative_program_avg_price_nok,
    cumulative_program_amount_nok, treasury_shares_after, source_document_id
)
SELECT p.id,
       t.period_start,
       t.period_end,
       t.shares,
       t.avg_price_nok,
       t.amount_nok,
       t.cumulative_shares,
       t.cumulative_avg_price_nok,
       t.cumulative_amount_nok,
       t.cumulative_shares,
       sd.id
FROM _otec_buyback_2023_h1_2024 t
JOIN buyback_programs p ON p.external_program_id='otec-buyback-2023-06-20'
JOIN sources s ON s.code='MANUAL'
JOIN source_documents sd ON sd.source_id=s.id AND sd.external_id=t.url
WHERE NOT EXISTS (
    SELECT 1 FROM buybacks b
    WHERE b.program_id=p.id AND b.trade_date=t.period_end
);

-- Attach/reconcile weekly cash movements. Daily attachment detail, if later ingested,
-- supersedes these weekly rows through the existing buyback_id logic.
UPDATE cash_movements
SET amount_nok = '-' || (
        SELECT t.amount_nok FROM _otec_buyback_2023_h1_2024 t
        WHERE t.period_end=cash_movements.movement_date
    ),
    amount_original = '-' || (
        SELECT t.amount_nok FROM _otec_buyback_2023_h1_2024 t
        WHERE t.period_end=cash_movements.movement_date
    ),
    currency = 'NOK',
    fx_rate_to_nok = '1',
    description = 'Otello buyback: ' || (
        SELECT CAST(t.shares AS TEXT) FROM _otec_buyback_2023_h1_2024 t
        WHERE t.period_end=cash_movements.movement_date
    ) || ' shares during ' || (
        SELECT t.period_start FROM _otec_buyback_2023_h1_2024 t
        WHERE t.period_end=cash_movements.movement_date
    ) || '–' || cash_movements.movement_date || '.',
    buyback_id = (
        SELECT b.id
        FROM buybacks b
        JOIN buyback_programs p ON p.id=b.program_id
        WHERE p.external_program_id='otec-buyback-2023-06-20'
          AND b.trade_date=cash_movements.movement_date
        ORDER BY b.id LIMIT 1
    ),
    source_document_id = COALESCE(
        source_document_id,
        (
            SELECT b.source_document_id
            FROM buybacks b
            JOIN buyback_programs p ON p.id=b.program_id
            WHERE p.external_program_id='otec-buyback-2023-06-20'
              AND b.trade_date=cash_movements.movement_date
            ORDER BY b.id LIMIT 1
        )
    ),
    confidence = 'CONFIRMED'
WHERE movement_type='OTELLO_BUYBACK'
  AND EXISTS (
      SELECT 1 FROM _otec_buyback_2023_h1_2024 t
      WHERE t.period_end=cash_movements.movement_date
  );

INSERT INTO cash_movements(
    movement_date, movement_type, amount_nok, amount_original, currency,
    fx_rate_to_nok, description, source_document_id, confidence, buyback_id
)
SELECT t.period_end,
       'OTELLO_BUYBACK',
       '-' || t.amount_nok,
       '-' || t.amount_nok,
       'NOK',
       '1',
       'Otello buyback: ' || CAST(t.shares AS TEXT) || ' shares during ' ||
           t.period_start || '–' || t.period_end || '.',
       b.source_document_id,
       'CONFIRMED',
       b.id
FROM _otec_buyback_2023_h1_2024 t
JOIN buyback_programs p ON p.external_program_id='otec-buyback-2023-06-20'
JOIN buybacks b ON b.program_id=p.id AND b.trade_date=t.period_end
WHERE NOT EXISTS (
    SELECT 1 FROM cash_movements c
    WHERE c.movement_type='OTELLO_BUYBACK' AND c.buyback_id=b.id
);

-- Weekly treasury share points make the per-share history continuous. Report anchors
-- at 2023-12-31 and 2024-06-30 remain untouched and provide independent controls.
UPDATE otello_share_counts
SET total_shares=91099729,
    treasury_shares=(
        SELECT t.cumulative_shares FROM _otec_buyback_2023_h1_2024 t
        WHERE t.period_end=otello_share_counts.effective_from
    ),
    outstanding_shares=91099729-(
        SELECT t.cumulative_shares FROM _otec_buyback_2023_h1_2024 t
        WHERE t.period_end=otello_share_counts.effective_from
    ),
    notes='Treasury shares from weekly curated official backfill; effective at period end ' ||
          effective_from || '.'
WHERE notes LIKE 'Treasury shares from weekly %'
  AND EXISTS (
      SELECT 1 FROM _otec_buyback_2023_h1_2024 t
      WHERE t.period_end=otello_share_counts.effective_from
  );

INSERT INTO otello_share_counts(
    effective_from, effective_to, total_shares, treasury_shares,
    outstanding_shares, source_document_id, notes
)
SELECT t.period_end,
       NULL,
       91099729,
       t.cumulative_shares,
       91099729-t.cumulative_shares,
       b.source_document_id,
       'Treasury shares from weekly curated official backfill; effective at period end ' ||
           t.period_end || '.'
FROM _otec_buyback_2023_h1_2024 t
JOIN buyback_programs p ON p.external_program_id='otec-buyback-2023-06-20'
JOIN buybacks b ON b.program_id=p.id AND b.trade_date=t.period_end
WHERE NOT EXISTS (
    SELECT 1 FROM otello_share_counts sc
    WHERE sc.effective_from=t.period_end
      AND sc.notes LIKE 'Treasury shares from weekly %'
);

DROP TABLE _otec_buyback_2023_h1_2024;

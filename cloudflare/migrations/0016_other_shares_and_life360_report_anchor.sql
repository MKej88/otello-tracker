-- Make the investor-facing 1H26 composition source-backed and independently splittable.
-- Otello 1H26 reports Investments in other shares = USD 3.936m as of 2026-06-30.
ALTER TABLE other_net_assets_reported_anchors
    ADD COLUMN other_shares_investment_reported TEXT;

UPDATE other_net_assets_reported_anchors
SET other_shares_investment_reported = CASE as_of_date
    WHEN '2025-06-30' THEN '820000'
    WHEN '2025-12-31' THEN '820000'
    WHEN '2026-06-30' THEN '3936000'
    ELSE other_shares_investment_reported
END
WHERE as_of_date IN ('2025-06-30', '2025-12-31', '2026-06-30');

-- Existing populated production D1 needs the 1H26 Life360 report-date close even if
-- the historical Yahoo/LSEG backfill was unavailable when the report was ingested.
-- A fresh D1 that is about to receive the deterministic historical bootstrap must NOT
-- seed this DATA_TABLE row here: the bootstrap carries the canonical source_document
-- and market_price IDs from SQLite. Guarding on existing NAV data cleanly distinguishes
-- an in-place production upgrade from a fresh schema/bootstrap target.
INSERT OR IGNORE INTO source_documents(
    source_id, external_id, document_type, title, published_at, url, metadata_json
)
SELECT id,
       'life360-ir-lseg:lif:2026-06-30:curated-report-anchor',
       'WEB_PAGE',
       'Life360 LIF historic close 2026-06-30 — LSEG',
       '2026-06-30T20:00:00Z',
       'https://investors.life360.com/stock-information/historic-price-lookup',
       '{"provider":"LSEG via Life360 Investor Relations","price_type":"historical_closing_price","source_policy":"CURATED_REPORT_ANCHOR_BACKFILL","report_anchor":"2026-06-30"}'
FROM sources
WHERE code='LIFE360_IR_LSEG'
  AND EXISTS (SELECT 1 FROM nav_snapshots LIMIT 1);

INSERT OR IGNORE INTO market_prices(
    instrument_id, observed_at, trading_date, price_type, price, currency,
    source_id, source_document_id, quality, metadata_json
)
SELECT i.id,
       '2026-06-30T20:00:00Z',
       '2026-06-30',
       'CLOSE',
       '55.36',
       'USD',
       s.id,
       sd.id,
       'DIRECT',
       '{"provider":"LSEG via Life360 Investor Relations","role":"NASDAQ_COMMON","source_policy":"CURATED_REPORT_ANCHOR_BACKFILL","report_anchor":"2026-06-30"}'
FROM instruments i
JOIN sources s ON s.code='LIFE360_IR_LSEG'
JOIN source_documents sd
  ON sd.source_id=s.id
 AND sd.external_id='life360-ir-lseg:lif:2026-06-30:curated-report-anchor'
WHERE i.symbol='LIF';

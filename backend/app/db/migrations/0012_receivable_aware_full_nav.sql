ALTER TABLE other_net_assets_reported_anchors
    ADD COLUMN associated_receivable_reported TEXT NOT NULL DEFAULT '0';

ALTER TABLE other_net_assets_reported_anchors
    ADD COLUMN base_other_net_assets_reported TEXT;

ALTER TABLE other_net_assets_daily_estimates
    ADD COLUMN base_amount_usd TEXT;

ALTER TABLE other_net_assets_daily_estimates
    ADD COLUMN base_amount_nok TEXT;

ALTER TABLE other_net_assets_daily_estimates
    ADD COLUMN associated_receivable_nok TEXT NOT NULL DEFAULT '0';

ALTER TABLE other_net_assets_daily_estimates
    ADD COLUMN receivable_quality TEXT NOT NULL DEFAULT 'NONE';

ALTER TABLE other_net_assets_daily_estimates
    ADD COLUMN receivable_components_json TEXT;

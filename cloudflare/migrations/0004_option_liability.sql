ALTER TABLE other_net_assets_reported_anchors
    ADD COLUMN option_liability_reported TEXT NOT NULL DEFAULT '0';

ALTER TABLE other_net_assets_reported_anchors
    ADD COLUMN base_other_net_assets_ex_option_reported TEXT;

ALTER TABLE other_net_assets_daily_estimates
    ADD COLUMN option_liability_nok TEXT NOT NULL DEFAULT '0';

ALTER TABLE other_net_assets_daily_estimates
    ADD COLUMN option_liability_usd TEXT NOT NULL DEFAULT '0';

ALTER TABLE other_net_assets_daily_estimates
    ADD COLUMN option_fair_value_per_option_nok TEXT;

ALTER TABLE other_net_assets_daily_estimates
    ADD COLUMN option_recognition_fraction TEXT;

ALTER TABLE other_net_assets_daily_estimates
    ADD COLUMN option_spot_nok TEXT;

ALTER TABLE other_net_assets_daily_estimates
    ADD COLUMN option_strike_nok TEXT;

ALTER TABLE other_net_assets_daily_estimates
    ADD COLUMN option_quality TEXT NOT NULL DEFAULT 'NONE';

ALTER TABLE other_net_assets_daily_estimates
    ADD COLUMN option_inputs_json TEXT;

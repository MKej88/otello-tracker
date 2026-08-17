ALTER TABLE corporate_actions ADD COLUMN external_action_id TEXT;
ALTER TABLE corporate_actions ADD COLUMN gross_amount_per_share TEXT;
ALTER TABLE corporate_actions ADD COLUMN net_amount_per_share TEXT;
ALTER TABLE corporate_actions ADD COLUMN gross_total_amount TEXT;
ALTER TABLE corporate_actions ADD COLUMN net_total_amount TEXT;
ALTER TABLE corporate_actions ADD COLUMN withholding_rate TEXT;
ALTER TABLE corporate_actions ADD COLUMN tax_treatment TEXT;
ALTER TABLE corporate_actions ADD COLUMN component_group TEXT;

CREATE UNIQUE INDEX idx_corporate_actions_external_action_id
    ON corporate_actions(external_action_id)
    WHERE external_action_id IS NOT NULL;

CREATE INDEX idx_corporate_actions_component_group
    ON corporate_actions(component_group)
    WHERE component_group IS NOT NULL;

ALTER TABLE cash_movements ADD COLUMN external_movement_id TEXT;

CREATE UNIQUE INDEX idx_cash_movements_external_movement_id
    ON cash_movements(external_movement_id)
    WHERE external_movement_id IS NOT NULL;

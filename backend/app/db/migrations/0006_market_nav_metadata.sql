-- Distinguish a complete NAV from a deliberately partial/core reconstruction.
ALTER TABLE nav_snapshots
    ADD COLUMN nav_scope TEXT NOT NULL DEFAULT 'FULL'
    CHECK (nav_scope IN ('FULL', 'CORE'));

ALTER TABLE nav_snapshots
    ADD COLUMN components_json TEXT NOT NULL DEFAULT '{}';

ALTER TABLE nav_snapshots
    ADD COLUMN quality_notes TEXT;

CREATE INDEX idx_nav_snapshots_scope_time
    ON nav_snapshots(nav_scope, as_of_at);

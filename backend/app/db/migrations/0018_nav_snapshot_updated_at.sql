-- Keep reference SQLite semantics aligned with production D1.
-- This intentionally fills the existing 0018 migration gap so the repository's
-- established bootstrap migration ceiling remains 0031.
ALTER TABLE nav_snapshots
    ADD COLUMN updated_at TEXT;

UPDATE nav_snapshots
SET updated_at = created_at
WHERE updated_at IS NULL;

CREATE TRIGGER IF NOT EXISTS nav_snapshots_set_updated_at_after_insert
AFTER INSERT ON nav_snapshots
FOR EACH ROW
WHEN NEW.updated_at IS NULL
BEGIN
    UPDATE nav_snapshots
    SET updated_at = NEW.created_at
    WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS nav_snapshots_touch_updated_at_after_update
AFTER UPDATE ON nav_snapshots
FOR EACH ROW
WHEN NEW.updated_at IS OLD.updated_at
BEGIN
    UPDATE nav_snapshots
    SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    WHERE id = NEW.id;
END;

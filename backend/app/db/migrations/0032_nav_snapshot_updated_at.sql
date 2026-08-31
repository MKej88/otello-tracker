-- Keep reference SQLite semantics aligned with production D1.
-- A NAV row can be recalculated in place several times during the same trading day.
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

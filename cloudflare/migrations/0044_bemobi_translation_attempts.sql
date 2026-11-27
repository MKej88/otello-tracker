-- Tell faktiske behandlingsforsøk, også ved avbrutt Workflow.
ALTER TABLE source_documents ADD COLUMN translation_attempts INTEGER NOT NULL DEFAULT 0;

ALTER TABLE source_documents ADD COLUMN original_language TEXT;
ALTER TABLE source_documents ADD COLUMN extraction_status TEXT;
ALTER TABLE source_documents ADD COLUMN translation_status TEXT;
ALTER TABLE source_documents ADD COLUMN summary_status TEXT;
ALTER TABLE source_documents ADD COLUMN norwegian_title TEXT;
ALTER TABLE source_documents ADD COLUMN norwegian_summary TEXT;
ALTER TABLE source_documents ADD COLUMN translated_pdf_key TEXT;
ALTER TABLE source_documents ADD COLUMN translation_error TEXT;
ALTER TABLE source_documents ADD COLUMN translation_processed_at TEXT;
ALTER TABLE source_documents ADD COLUMN translator_model TEXT;
ALTER TABLE source_documents ADD COLUMN translator_version TEXT;
ALTER TABLE source_documents ADD COLUMN translation_character_count INTEGER;

CREATE INDEX idx_source_documents_translation_queue
    ON source_documents(translation_status, id);

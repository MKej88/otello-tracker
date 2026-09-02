-- Legg til en eksplisitt, utvidbar identifikasjon uten å bygge om tabellen.
-- movement_type beholdes for bakoverkompatibilitet med eksisterende kontantbro.
ALTER TABLE cash_movements ADD COLUMN identified_type TEXT;

UPDATE cash_movements
SET identified_type = 'PATENT_PROCEEDS'
WHERE instr(
    external_movement_id,
    'otello-report-post-cash:PATENT_SALE_FINAL_INSTALMENT:'
) = 1;

CREATE INDEX idx_cash_movements_identified_type
    ON cash_movements(identified_type);

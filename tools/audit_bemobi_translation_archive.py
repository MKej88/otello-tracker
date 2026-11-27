"""Read-only inventory of the historical Bemobi document archive in D1.

Aggregate metadata only. Never log URLs, document text, credentials or raw errors.
"""
from __future__ import annotations

import json

from reactivate_bemobi_translation_documents import d1_client

BASE = """
WITH inventory AS (
    SELECT s.code AS source,
           CASE WHEN substr(sd.published_at,1,4) GLOB '[0-9][0-9][0-9][0-9]'
                THEN substr(sd.published_at,1,4) ELSE 'UNKNOWN' END AS year,
           CASE WHEN sd.translation_status IN ('READY','PENDING','PROCESSING','FAILED','NOT_REQUIRED')
                THEN sd.translation_status
                WHEN sd.translation_status IS NULL OR trim(sd.translation_status)=''
                THEN 'UNQUEUED' ELSE 'OTHER' END AS status,
           CASE WHEN s.code='CVM' AND sd.document_type='CVM_IPE_METADATA' THEN 'CVM_IPE_METADATA'
                WHEN s.code='CVM' THEN 'CVM_OTHER'
                WHEN upper(sd.document_type) LIKE '%PDF%' THEN 'IR_PDF'
                WHEN lower(sd.url) LIKE '%.pdf' OR lower(sd.url) LIKE '%.pdf?%' THEN 'IR_PDF_URL'
                ELSE 'IR_OTHER' END AS kind,
           CASE WHEN s.code<>'CVM' THEN 'NOT_APPLICABLE'
                WHEN json_valid(sd.metadata_json) THEN
                    CASE json_extract(sd.metadata_json,'$.is_latest_version')
                        WHEN 1 THEN 'LATEST' WHEN 0 THEN 'SUPERSEDED' ELSE 'UNKNOWN' END
                ELSE 'UNKNOWN' END AS version,
           CASE WHEN sd.translation_attempts>=3 THEN 1 ELSE 0 END AS exhausted,
           CASE WHEN sd.translated_pdf_key IS NOT NULL AND trim(sd.translated_pdf_key)<>'' THEN 1 ELSE 0 END AS has_pdf,
           CASE WHEN sd.norwegian_summary IS NOT NULL AND trim(sd.norwegian_summary)<>'' THEN 1 ELSE 0 END AS has_summary
    FROM source_documents sd JOIN sources s ON s.id=sd.source_id
    WHERE s.code IN ('CVM','BEMOBI_IR')
)
"""
COUNTS = BASE + """
SELECT source, year, COUNT(*) AS total,
       SUM(status='READY') AS ready, SUM(status='PENDING') AS pending,
       SUM(status='PROCESSING') AS processing, SUM(status='FAILED') AS failed,
       SUM(status='FAILED' AND exhausted=1) AS exhausted,
       SUM(status='NOT_REQUIRED') AS not_required, SUM(status='UNQUEUED') AS unqueued,
       SUM(status='OTHER') AS other,
       SUM(status='READY' AND has_pdf=0) AS ready_without_pdf,
       SUM(status='READY' AND has_summary=0) AS ready_without_summary
FROM inventory GROUP BY source,year ORDER BY source,year
"""
DETAIL = BASE + """
SELECT source, year, kind, version, status, COUNT(*) AS total
FROM inventory
WHERE status IN ('UNQUEUED','FAILED','OTHER','NOT_REQUIRED')
GROUP BY source,year,kind,version,status ORDER BY source,year,kind,version,status
"""
VERSIONS = BASE + """
SELECT source,version,status,COUNT(*) AS total
FROM inventory GROUP BY source,version,status ORDER BY source,version,status
"""
# All values from these queries are fixed classifications, numeric years or counts.
# No row-level titles, URLs or source content leave D1.

def report(query):
    for name, sql in (("ARKIV_PER_ÅR", COUNTS), ("UAVKLARTE_PER_TYPE", DETAIL),
                      ("VERSJONER_OG_STATUS", VERSIONS)):
        rows = query(sql, ())["results"]
        print(name + ": " + json.dumps(rows, ensure_ascii=False, sort_keys=True))
    print("Skrivebeskyttet kartlegging fullført; ingen dokumenter endret.")


if __name__ == "__main__":
    report(d1_client("CLOUDFLARE_READ_TOKEN"))

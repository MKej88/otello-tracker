from pathlib import Path

path = Path('backend/tests/test_cloudflare_newsweb_ingestion.py')
text = path.read_text(encoding='utf-8')
old = '''def test_worker_newsweb_persists_disclosed_maximum_purchase_price_with_provenance() -> None:\n    repository = SqliteD1Repository()\n    try:\n        body = FIRST_WEEK_2023.replace("NOK 15 per share", "NOK 20 per share")\n'''
new = '''def test_worker_newsweb_persists_disclosed_maximum_purchase_price_with_provenance() -> None:\n    repository = SqliteD1Repository()\n    try:\n        seed_document = asyncio.run(\n            repository.create_source_document(\n                source_code="NEWSWEB",\n                document_type="REGULATORY_NEWS",\n                title="Share-count test fixture",\n                url="https://newsweb.oslobors.no/message/share-count-fixture",\n            )\n        )\n        repository.connection.execute(\n            """\n            INSERT INTO otello_share_counts(\n                effective_from, total_shares, treasury_shares, outstanding_shares,\n                source_document_id, notes\n            ) VALUES ('2023-06-20', 91099711, 0, 91099711, ?, 'test fixture')\n            """,\n            (seed_document,),\n        )\n        repository.connection.commit()\n\n        body = FIRST_WEEK_2023.replace("NOK 15 per share", "NOK 20 per share")\n'''
if old not in text:
    raise SystemExit('NewsWeb max-price test marker missing')
path.write_text(text.replace(old, new, 1), encoding='utf-8')

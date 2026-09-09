# Norsk oversettelse av Bemobi-dokumenter

Nye, gjeldende CVM-dokumenter legges i behandlingskø når den daglige workflowen
registrerer dem. Original-URL-en endres aldri. Workflowen henter PDF-en, bruker
`pypdf` til vanlig tekstuttrekk, oppdager språk fra innholdet, oversetter
portugisisk tekst i nummererte deler og validerer tall, prosenter, valuta og datoer.
Den norske PDF-en lagres innholdsadressert i den eksisterende
`SOURCE_ARCHIVE`-bøtten. Dokumenter uten lesbar tekst feiler trygt med beskjed om
at OCR er nødvendig; det kjøres ikke kostbar OCR på PDF-er som allerede har tekst.

## Produksjonsoppsett

Ingen ny Cloudflare-ressurs er nødvendig. Kjør migrasjon `0033`, og sett secret:

```bash
cd cloudflare
npx wrangler secret put BEMOBI_TRANSLATION_API_KEY
```

Sett eventuelt `BEMOBI_TRANSLATION_MODEL` og `BEMOBI_TRANSLATION_ENDPOINT` som
Worker-variabler. Uten secret fortsetter all nyhetsinnhenting normalt, mens
oversettelsessteget hoppes over.

## Kontrollert backfill

Funksjonen `queue_translation_backfill` kan kalles fra en kontrollert
driftsjobb med enten `document_id`, `after` (ISO-dato) og/eller `limit`. Ingen
historiske dokumenter køes automatisk av migrasjonen. For ett dokument: kall
funksjonen med `document_id=<id>, limit=1`, og start deretter full-refresh-workflowen.

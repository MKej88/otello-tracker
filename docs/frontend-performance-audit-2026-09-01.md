# Målrettet frontend-audit, 1. september 2026

## Arkitektur og viktigste innganger

Frontend er en Vite/React-applikasjon med `main.tsx` som eneste HTML-inngang.
`InvestorApp` viser Oversikt direkte og deler de øvrige åtte visningene i egne
JavaScript-biter. Data til førstesiden samles i ett bootstrap-kall, mens
navigasjon starter både kode- og datahenting før den valgte visningen monteres.

Produksjon har to leveringsveier:

- Cloudflare bruker `public/_headers` og gir innholdshash-baserte filer ett års
  immutable cache.
- Docker-bildet bruker `frontend/nginx.conf`. Denne veien hadde verken eksplisitt
  komprimering eller caching av `/assets/`.

## Undersøkte kandidater og prioritering

| Kandidat | Observasjon/måling | Vurdering |
| --- | --- | --- |
| Komprimering i nginx | Førsteskjermens JS + CSS er 238,78 kB ukomprimert og 73,27 kB gzip i Vite-målingen. | Høy effekt, høy sikkerhet, svært lav risiko. Valgt. |
| Cache av hash-filer i nginx | Cloudflare har ett års immutable cache, nginx hadde ingen `Cache-Control` for `/assets/`. | Høy effekt ved gjenbesøk, høy sikkerhet, lav risiko. Valgt. |
| Bundle/code splitting | Første JS-bit er 215,48 kB (67,70 kB gzip). De øvrige visningene er allerede lazy-lastet i biter på 0,20–25,95 kB. React/ReactDOM står for klart mesteparten av kildekoden i sourcemap. | Ingen trygg, materiell reduksjon uten arkitekturbytte. Ikke valgt. |
| Requests/waterfalls | Bootstrap samler fire førsteskjermressurser. Navigasjon gjenbruker påbegynt request og starter data og kode parallelt. | Ingen dokumentert duplikat eller sekvensiell flaskehals. Ikke valgt. |
| Renderarbeid/lister | Ingen store tredjepartsavhengigheter utover React, og ingen ubegrensede tabeller ble funnet på førsteskjermen. Polling er satt til to minutter og beskytter mot overlappende kall. | Profilering i ekte browser kreves før eventuell React-optimalisering. Ikke valgt. |
| Bilder, fonter og layoutskift | Ingen eksterne bilder eller fonter lastes på førsteskjermen. Kortene har lastetilstander. | Ikke en materiell kandidat i denne gjennomgangen. |

Prioriteringen følger effekt × sikkerhet ÷ kompleksitet/risiko. Det ble ikke lagt
til `memo`, `useMemo` eller generell refaktorering uten en målt flaskehals.

## Endring 1: komprimer tekstressurser i nginx

**Flaskehals:** Docker/nginx kunne overføre Vite-filene ukomprimert, selv om de
komprimerer godt. Det øker tiden før JavaScript kan parses og siden blir
interaktiv på trege forbindelser.

**Samme målemetode før og etter:** `npm run build` sin rapport for den initiale
JS- og CSS-biten.

- Før: 215,48 + 23,30 = **238,78 kB** overført uten HTTP-komprimering.
- Etter: 67,70 + 5,57 = **73,27 kB** når klienten støtter gzip.
- Reduksjon: **165,51 kB / 69,3 %**.

nginx komprimerer nå JavaScript, CSS og JSON og sender `Vary: Accept-Encoding`.
Dette endrer ikke innhold eller datakorrekthet. CPU-kostnaden er litt komprimering
på serveren; de statiske filene er små, og gevinsten på nettverket er vesentlig.

## Endring 2: cache innholdshash-baserte filer

**Flaskehals:** Docker/nginx ga ikke `/assets/` den cache-policyen Cloudflare
allerede bruker. Dermed var rask gjenbruk av samme JS og CSS avhengig av
nettleserens heuristikk og kunne gi nye valideringsrequests ved gjenbesøk.

- Før: **0 eksplisitt cachede asset-ruter** i nginx.
- Etter: **1 asset-rute** med `max-age=31536000, immutable`.
- For en varm cache kan de **238,78 kB** statiske førsteskjermressursene gjenbrukes
  uten nettverksrequest. HTML og API-data omfattes ikke og forblir ferske.

## Avgrensninger

Miljøet hadde ikke Chrome/Chromium eller nginx-binær, så LCP, INP, CLS og faktiske
HTTP-headere kunne ikke måles lokalt. Bundlemålingen er reproduserbar, og
konfigurasjonen er kontrollert med Python-tester. En produksjonsmåling med ekte
nettverksprofil er derfor neste steg, ikke flere udokumenterte kodeendringer.

## Resultat

- **Viktigste flaskehals før:** ukomprimerte, ikke eksplisitt cachede assets i
  Docker/nginx-leveransen.
- **Endringer gjort:** gzip for tekstressurser og ett års immutable cache for
  Vite sine hash-navngitte `/assets/`.
- **Måling før:** 238,78 kB initial JS + CSS uten HTTP-komprimering.
- **Måling etter:** 73,27 kB initial JS + CSS med gzip.
- **Forbedring:** 165,51 kB, eller 69,3 % mindre overføring for disse filene.
- **Trade-offs:** liten CPU-kostnad til gzip; nye bygg må fortsatt bruke
  innholdshash, slik Vite allerede gjør.
- **Neste mest lovende forbedring:** mål LCP og main-thread-tid i produksjon på
  mobil. Hvis React-biten faktisk dominerer, vurder først da om en liten del av
  Oversikt under folden bør splittes videre.

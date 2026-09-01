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

## Oppfølging: navigasjon til Datakvalitet

En ny gjennomgang av hele navigasjonsstien fant én konkret request-waterfall som
ikke var dekket av den første auditen:

1. **Startpunkt:** klikk, fokus eller bevisst hover på «Datakvalitet».
2. Ruteren startet JavaScript-modulen og to API-kall parallelt.
3. Først etter at modulen var lastet, tolket og React hadde montert visningen,
   startet `/api/bemobi/source-status`.
4. **Sluttpunkt:** kortet «Datakilder» kunne vise korrekt kildestatus.

Det tredje API-kallet avhenger ikke av runtime- eller rapportstatus. Avhengigheten
til ferdig modulinnlasting var derfor ikke reell. Før endringen var tiden til
kildestatus omtrent `modultid + API-tid`; etter endringen er den omtrent den
lengste av de to. Med eksempelvis 250 ms modulinnlasting og 400 ms API-latency
blir critical path redusert fra 650 til 400 ms, altså 250 ms. Den faktiske
gevinsten tilsvarer modulens resterende innlastingstid og bør måles i produksjon.

| Kandidat | Effekt | Sikkerhet | Risiko/kompleksitet | Beslutning |
| --- | --- | --- | --- | --- |
| Start kildestatus sammen med Datakvalitet-modulen | Fjerner én dokumentert sekvens og sparer opptil hele modultiden | Høy; endepunktene er uavhengige | Lav; eksisterende request-gjenbruk, caching og polling beholdes | Implementert |
| Preload alle visninger ved oppstart | Kan gjøre senere navigasjon raskere | Lav; konkurrerer med førstesiden og kan hente data som aldri brukes | Middels | Avvist |
| Memoiser Datakvalitet-komponentene | Ukjent uten React-profil | Lav | Middels og kan skjule state-feil | Avvist |

Kildestatus bruker nå samme pollingmekanisme som de to andre ressursene. Den
mekanismen gjenbruker den påbegynte navigasjonsrequesten, beholder 30 sekunders
cache, stopper overlappende polling, avbryter ordinære requests ved avmontering og
viser fortsatt siste gode data ved oppdateringsfeil. Datakorrekthet, caching og
feilhåndtering blir dermed ikke svekket.

# Målrettet frontend-audit, 8. september 2026

## Metode og critical path

Gjennomgangen fulgte førstegangsbesøket fra HTML, via modulinnlasting og
bootstrap-kallet, til React kan vise korrekte nøkkeltall. Produksjonsbygget ble
brukt for størrelser, og request-alternativene i HTML og `fetch` ble sammenlignet
for å kontrollere om nettleserens preload faktisk kunne gjenbrukes. Miljøet har
ikke Chrome/Chromium, så veggklokketid er estimert fra den dokumenterte
request-stien og ikke presentert som en nettlesermåling.

## Kandidater

| Kandidat | Startpunkt → sluttpunkt | Måling/estimat | Avhengighet og vurdering |
| --- | --- | --- | --- |
| Bootstrap ble hentet med ulike cachevalg | HTML-parser starter preload → JavaScript starter `fetch` med `no-cache` → samme bootstrap må revalideres → nøkkeltall kan vises | Før kunne ett planlagt bootstrap-kall bli fulgt av én tvungen revalidering. Det tilfører opptil en ekstra nettverksrunde og konkurrerer med inngangspakken på 68,60 kB gzip. Anslått 50–200 ms ved vanlig mobil-latens, mer ved Worker-oppstart. Etter er requestene like og nettleseren kan gjenbruke preload-responsen. | `no-cache` var ikke en dataavhengighet. HTML-preloaden er selve nettverksforespørselen, og API-et har allerede en kort HTTP-cache. Høy effekt og sikkerhet, svært lav kompleksitet. **Valgt.** |
| Splitte Oversikt videre | HTML → JavaScript → første React-render | Inngangspakken er 217,11 kB / 68,60 kB gzip. | React/ReactDOM dominerer, og splitting av synlig oversiktskode kan bare flytte, ikke fjerne, en kritisk modulrequest. Lavere sikkerhet og høyere render-risiko. Ikke valgt. |
| Memoisering av Oversikt | API-state → React-render → paint | Seks små svar, små lister og enkel aritmetikk. | Ingen dokumentert materiell CPU-kostnad. Ikke endret. |
| Backend-latency | Bootstrap-start → bootstrap-svar | Serveren leser normalt ett ferdig hot snapshot; responsen rapporterer `server_ms`. | Kan dominere ved Worker-/D1-latency, men en ekstra klientrevalidering gjorde ventingen verre. Ingen backendendring er nødvendig for valgt forbedring. |

## Valgt forbedring

JavaScript bruker nå samme standard requestvalg som HTML-preloaden. Critical path
endres fra

`HTML → preload + inngangspakke → fetch(no-cache) / mulig revalidering → render`

til

`HTML → preload + inngangspakke → gjenbruk av preload → render`.

Endringen fjerner ingen ferskhetsmekanisme: preloaden gjør fortsatt et ordinært
nettverkskall, bootstrap-endepunktets HTTP-cache bestemmer tillatt alder, den
avgrensede siste-gode kopien brukes fortsatt for rask gjenvisning, og ferske
nettverksdata publiseres fortsatt til monterte komponenter. HTTP-statuskontroll,
payload-validering, fallback til dedikerte endepunkter og error handling er
uendret.

## Før og etter

Samme statiske metode gir:

- **Før:** HTML-request med standard cachevalg og JavaScript-request med eksplisitt
  `no-cache`; opptil to nettverkshandlinger for samme URL.
- **Etter:** identisk URL, metode, credentials og cachevalg; én preload-respons kan
  betjene JavaScript-konsumenten.
- **Requestreduksjon:** opptil 1 av 2 bootstrap-nettverkshandlinger, altså 50 % på
  denne delen av førstegangsstien.
- **Bygg:** inngangspakken er fortsatt 217,11 kB / 68,60 kB gzip; endringen legger
  ikke til kode eller avhengigheter.

Kontrakttesten låser at `fetch` ikke senere får et cachevalg som bryter samsvaret
med HTML-preloaden. Faktisk spart tid og request-gjenbruk bør i tillegg bekreftes
i produksjonens Network-panel.

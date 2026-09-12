# Undersøkelse av frontendens critical path (2026-09-12)

## Metode og avgrensning

Produksjonsbygg, kildekode og request-rekkefølge ble undersøkt fra HTML til
ferdig React-visning. `npm run build` målte inngangsbunten til 68,78 kB gzip.
Produksjonsendepunktene kunne ikke tidsmåles fra arbeidsmiljøet fordi
nettverkstunnelen svarte 403. Backend-tid er derfor ikke brukt som grunnlag for
endringen.

## Dokumentert flaskehals

Ved direkte åpning av en hash-rute, for eksempel `#nav`, var startpunktet
nettleserens behandling av HTML-en. API-kallene startet først ved sluttpunktet
der inngangsbunten var lastet, tolket, kjørt og rutens `preload()` var nådd.
Deretter måtte den kode-splittede rutemodulen lastes før React kunne montere
visningen. Data og rutemodul kunne ha blitt hentet parallelt, men gjorde det
ikke før inngangsbunten var ferdig.

Inngangsbunten tilfører alene omtrent 344 ms ren overføring ved 1,6 Mbit/s
(68,78 kB × 8 / 1,6 Mbit/s), i tillegg til nettverksforsinkelse, JavaScript-
tolking og kjøring. På 10 Mbit/s er samme nedre grense omtrent 55 ms. Etter
endringen opprettes preload-requestene direkte fra HTML, før modulscriptet, så
denne ventetiden fjernes fra starten av datahentingen.

Avhengigheten var ikke reell: sidene startet allerede de samme uavhengige
requestene parallelt i `preload()`, og komponentene håndterer hvert svar og hver
feil separat. Endringen flytter bare starttidspunktet og endrer verken payload,
caching eller feilbehandling. Nettlesercachen lar de eksisterende fetch-kallene
gjenbruke preload-svarene.

## Vurderte kandidater

| Kandidat | Start → slutt | Målt/estimert tillegg | Impact × confidence ÷ risiko | Valg |
| --- | --- | --- | --- | --- |
| API starter etter inngangsbunten ved direkte rute | HTML → `preload()` i inngangsbunten | minst ca. 55–344 ms ved 10–1,6 Mbit/s, pluss tolking | høy × høy ÷ lav | implementert |
| NAV-bunten venter på synlig 1M-historikk | første periode → øvrige perioder | 0 ms for synlig standardperiode; ventingen beskytter båndbredden | lav × høy ÷ middels | beholdt |
| Store rutekomponenter | ruteimport → modul ferdig | største rutebunt 6,22 kB gzip | lav × høy ÷ middels | ingen endring |
| Backend-latency | request sendt → første byte | ikke målbart her (403 fra nettverkstunnel) | ukjent × lav ÷ høy | ingen endring |

## Resultat

Bare data som den valgte direkte ruten faktisk bruker, prelastes. Primærdata
har høy prioritet; supplerende data har lav prioritet for ikke å forsinke
rutemodulen. Navigasjon inne i applikasjonen beholder eksisterende
request-sammenslåing, caching og feiltilstander.

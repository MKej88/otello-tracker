# Undersøkelse av frontendens critical path (2026-09-19)

## Metode

Gjennomgangen fulgte første åpning og intern navigasjon fra brukerhandling via
ruting, modulinnlasting, API-kall, state og React-rendering. Produksjonsbygget og
en deterministisk request-test ble brukt. Miljøet har ikke Chrome/Chromium, så
layout og paint er ikke profilert, og det oppgis ikke konstruerte
produksjonsmålinger.

## Dokumentert flaskehals

På Oversikt venter fem synlige dataressurser normalt på ett samlet
`/api/dashboard/bootstrap`-kall. Dette er raskt når hot snapshot virker, men
fallback-stien hadde en request-waterfall:

`bootstrap-request → feil/timeout → dedikert API-request → nyttig innhold`.

Startpunktet var første datarequest fra React, og sluttpunktet var responsen fra
det dedikerte endepunktet. Hvis bootstrap brukte 10 sekunder før feil og det
dedikerte endepunktet brukte 300 ms, ble innholdet synlig etter omtrent 10,3
sekunder. Datarequesten var ikke avhengig av bootstrap-resultatet; ventingen var
bare en optimalisering for å unngå flere kall i normaltilfellet.

Frontend starter nå det dedikerte endepunktet som en sikring dersom bootstrap
fortsatt ikke har svart etter 750 ms. Med samme eksempel blir tiden omtrent
1,05 sekunder, en reduksjon på 9,25 sekunder. Svarer bootstrap innen 750 ms,
sendes fortsatt bare ett nettverkskall som før.

## Kandidater og prioritering

| Kandidat | Start → slutt | Tilført tid | Impact × confidence ÷ risiko | Valg |
| --- | --- | --- | --- | --- |
| Sekvensiell fallback etter treg bootstrap | Bootstrap-start → feil/timeout → dedikert svar | Hele bootstrap-ventetiden, potensielt til nettverkstimeout | høy × høy ÷ lav | implementert |
| Kode-splittede ruter | Klikk → modul ferdig | 2,5–6,2 kB gzip per rute | lav × høy ÷ middels | beholdt; data starter allerede parallelt |
| React/databehandling | API-svar → DOM | Små/memoiserte datasett; ingen materiell blokkering dokumentert | lav × middels ÷ middels | ingen endring |
| Vanlig backend-latens | Request → svar | Ikke målt lokalt | ukjent × lav ÷ høy | ingen backendendring |

## Korrekthet og risiko

Bootstrap er fortsatt førstevalg og lagres/publiseres som før. Sikringen bruker
samme dedikerte URL, requestvalg, statuskontroll og komponentenes eksisterende
feilhåndtering. Det kan komme ett ekstra kall bare når bootstrap passerer 750
ms; dette er den bevisste kostnaden for å hindre at en treg eller hengende samlet
request blokkerer hele førstesiden. En test holder bootstrap åpen og bekrefter at
det dedikerte svaret faktisk frigjør critical path.

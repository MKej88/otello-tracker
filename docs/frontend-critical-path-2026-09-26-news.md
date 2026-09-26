# Undersøkelse av frontendens critical path – Nyheter (2026-09-26)

## Metode

Gjennomgangen fulgte direkte åpning og intern navigasjon til **Nyheter** fra
hash-ruting og kode-splittet modul, via `/api/news-events`, D1-lesinger,
databehandling og React-state, til nyhetslisten og kalenderen er synlige. Et
produksjonsbygg dokumenterte klientkostnaden, og en kontrollert asynkron test
registrerte hvilke databaselesinger som faktisk var aktive samtidig. Miljøet
har ikke Chrome/Chromium eller produksjons-D1, så reell nettverks-, layout- og
paint-tid er ikke målt lokalt.

## Dokumentert flaskehals

Frontend startet både rutemodulen og API-kallet tidlig. Inne i Worker-kallet
oppstod likevel en request-waterfall:

`brukerhandling → routing/modul + API → nyhetslesing fra D1 → fire parallelle
kalenderlesinger fra D1 → samlet svar → React-state → nyttig innhold`.

Nyhetslisten og kalendergrunnlaget har ingen dataavhengighet. Kalenderkallene
bruker bare valgt dato, ikke resultatet fra nyhetskallet. Før endringen viste
den kontrollerte testen maksimalt fire samtidige lesinger: nyhetslesingen var
ferdig før de fire kalenderlesingene startet. Etter endringen er alle fem
aktive samtidig.

Den fjernede kostnaden er én hel D1-ventebølge når nyhetsresultatet passer i
første side. Med eksempelvis 30 ms per D1-rundtur går den rene ventetiden fra
omtrent 60 ms til 30 ms. Ved ekstra paginering kan kalendergrenen nå også bli
ferdig mens flere nyhetssider behandles. Dette er et estimat av strukturell
ventetid, ikke en påstand om målt produksjonslatens.

## Kandidater og prioritering

| Kandidat | Startpunkt → sluttpunkt | Tilført tid / mengde | Impact × confidence ÷ risiko | Valg |
| --- | --- | --- | --- | --- |
| Seriell nyhets- og kalendergren i Worker | første D1-lesing → alle data klare → API-svar | én unødvendig D1-ventebølge; ca. 30 ms i 30 ms-modellen | middels × høy ÷ lav | implementert |
| Kode-splittet Nyheter-modul | navigasjon → modul → React-render | 1,95 kB gzip | lav × høy ÷ middels | ikke endret |
| Klientfiltrering og rendering | API-svar → synlig liste | bare ti nyheter og åtte kalenderposter vises først | lav × høy ÷ middels | ikke endret |
| API-cache | request → cache/Worker | eksisterende HTTP-cache reduserer mange gjentatte treff | ukjent × middels ÷ høy | ikke endret |

## Før og etter

- **Før:** Nyhetslesingen måtte fullføres før de uavhengige
  kalenderlesingene startet.
- **Etter:** Nyheter og alle kalenderkilder starter i samme ventebølge; samlet
  respons venter fortsatt på begge grenene slik at innholdet er komplett.
- **Korrekthet:** SQL, parametere, paginering, sortering og responsformat er
  uendret. Bare starttidspunktet for uavhengige lesinger er flyttet.
- **Feilhåndtering og caching:** Endepunktets eksisterende feiloppførsel og
  HTTP-cache er uendret.

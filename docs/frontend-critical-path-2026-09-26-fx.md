# Undersøkelse av frontendens critical path – BRL/NOK (2026-09-26)

## Metode

Gjennomgangen fulgte direkte åpning og intern navigasjon fra brukerhandling via
ruting, kode-splittet modul, API-kall, state, React-rendering og synlig innhold.
Requestrekkefølgen ble kontrollert i ruteren og BRL/NOK-komponenten. Før- og
ettertilstanden ble bygget med samme produksjonskommando. Miljøet har ikke en
nettleser, så produksjonslatens, layout og paint er ikke målt lokalt.

## Dokumentert flaskehals

Ved intern navigasjon til **BRL/NOK** startet tre requests parallelt:

`klikk → ruting/preload → fx + summary + economic → state updates → render`.

`/api/dashboard/economic` leverte bare en reserveverdi for antall utestående
aksjer. Alle beregninger som kunne bruke reserveverdien krevde samtidig
Bemobi-verdi, kurs eller beholdning fra `/api/dashboard/summary`. Summary-svaret
har selv `shares_outstanding` når det er klart. Economic-svaret kunne derfor
ikke gjøre noe nyttig innhold komplett dersom summary manglet, og var ikke en
reell dataavhengighet.

Kallet blokkerte ikke de to nyttige svarene med `await`, men konkurrerte med
dem om nettverk, Worker- og databasekapasitet i samme critical path. Det ble
også gjentatt hvert tiende minutt og ga en egen state-oppdatering og render.

## Kandidater og prioritering

| Kandidat | Startpunkt → sluttpunkt | Tilført tid / mengde | Impact × confidence ÷ risiko | Valg |
| --- | --- | --- | --- | --- |
| Redundant economic-request på BRL/NOK | navigasjon → request/parsing → ubrukt reserveverdi/state/render | ett av tre kall ved intern navigasjon (33 % av kallantallet) og ett kall per 10 minutt | middels × svært høy ÷ svært lav | implementert |
| Kode-splittet BRL/NOK-modul | klikk → modul → første render | 5,70 kB gzip før, 5,69 kB etter | lav × høy ÷ middels | ikke endret |
| Databehandling av valutaserier | API-svar → diagram | lineære beregninger, memoiserte glidende snitt og ingen dokumentert langoppgave | lav × middels ÷ middels | ikke endret |
| Backend-latens i de nyttige kallene | request → respons | ikke målt representativt lokalt | ukjent × lav ÷ høy | ikke endret |

## Før og etter

- **Før:** tre API-kall ved intern navigasjon og tre periodiske kall hvert
  tiende minutt.
- **Etter:** to nødvendige API-kall ved navigasjon og ved polling, altså 33 %
  færre kall i denne visningens lastesyklus.
- **Byggstørrelse:** BRL/NOK-modulen gikk fra 18,05 kB / 5,70 kB gzip til
  17,99 kB / 5,69 kB gzip. Hovedgevinsten er spart request- og backendarbeid,
  ikke buntstørrelsen.
- **Korrekthet:** `summary.shares_outstanding` kommer fra samme svar som de
  øvrige obligatoriske grunnlagene for beregningene. Direkte åpning var allerede
  uten economic-preload. Caching og feilhåndtering for de to nødvendige kallene
  er uendret.

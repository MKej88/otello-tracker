# Undersøkelse av frontendens critical path (2026-09-26)

## Metode

Gjennomgangen fulgte direkte åpning og intern navigasjon fra brukerhandling via
ruting, modulinnlasting, API-kall, state og React-rendering. Requestrekkefølgen
ble kontrollert i HTML-en, ruteren og hver visnings data-hook. Et
produksjonsbygg ble brukt til å måle JavaScript-størrelsene. Miljøet har ikke
Chrome/Chromium, så reell Worker-latens, layout og paint er ikke målt lokalt.

## Dokumentert flaskehals

Ved direkte åpning av **Brasil** startet hovedkallet tidlig fra HTML-en, mens
`/api/dashboard/economic` først startet etter at inngangsbunten, rutingen og den
kode-splittede Brasil-modulen var lastet, tolket og kjørt:

`HTML → 77,65 kB gzip inngangskode → 5,14 kB gzip Brasil-modul → React-effect → economic-request → komplette NAV-tall`.

Economic-svaret leverer Bemobi-andelen av NAV som brukes i den synlige
BRL/NOK-forklaringen. Frem til svaret kommer viser siden makroinnhold, men
NAV-effekten og Bemobis andel av NAV blir stående som manglende verdier. Den
målbare ekstrakostnaden var derfor arbeidet med 82,79 kB gzip JavaScript før
requesten i det hele tatt kunne starte. Ved 1,6 Mbit/s tilsvarer overføringen
alene omtrent 414 ms; ved 10 Mbit/s omtrent 66 ms, i tillegg til
nettverksforsinkelse, parsing og React-montering.

Det finnes ingen dataavhengighet mellom Brasil- og economic-requesten. Intern
navigasjon startet allerede begge parallelt, og komponenten leser dem gjennom
to uavhengige polling-hooks. Etter endringen starter begge ved HTML-parsing på
direkte inngang. Brasil-data beholder høy prioritet, mens supplerende NAV-data
har lav prioritet for ikke å fortrenge hovedinnholdet.

## Kandidater og prioritering

| Kandidat | Startpunkt → sluttpunkt | Tilført tid / mengde | Impact × confidence ÷ risiko | Valg |
| --- | --- | --- | --- | --- |
| Sen economic-request ved direkte Brasil-inngang | HTML → modul/effect → economic-svar → komplette NAV-tall | Requeststart forsinket av 82,79 kB gzip kode; ca. 66–414 ms ren overføring ved 10–1,6 Mbit/s | middels × høy ÷ lav | implementert |
| Tre kjernekall på Cash | navigasjon → tregeste svar → full visning | alle tre svar kreves av nåværende fullvisning; faktisk endepunktlatens er ikke målt | middels × middels ÷ middels | ikke endret |
| Kode-splittede rutemoduler | klikk → modul → render | største rutemodul er 6,22 kB gzip | lav × høy ÷ middels | ikke endret |
| React/databehandling og DOM | API-svar → synlig side | synlige lister er små og tyngre beregninger er memoiserte; ingen målt langoppgave | lav × middels ÷ middels | ikke endret |
| Backend-latens | request → respons | ikke målt representativt lokalt | ukjent × lav ÷ høy | ingen backendendring |

## Før og etter

- **Før:** economic-requesten startet først etter 82,79 kB gzip kode, parsing og
  React-montering ved direkte åpning av Brasil.
- **Etter:** economic-requesten starter under HTML-parsing parallelt med
  hovedkallet og JavaScript.
- **Uendret:** API-URL, responsbehandling, 30-sekunders navigasjonscache,
  polling, feiltilstand og prioriteten til Brasil-sidens hoveddata.
- **Korrekthet:** Endringen flytter bare starttidspunktet. Den eksisterende
  data-hooken utfører fortsatt statuskontroll, parsing og state-oppdatering.

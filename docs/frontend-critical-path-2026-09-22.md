# Undersøkelse av frontendens critical path (2026-09-22)

## Metode

Gjennomgangen fulgte direkte åpning og intern navigasjon fra brukerhandling via
ruting, modulinnlasting, API-kall, state og React-rendering. Requestrekkefølgen
ble kontrollert i HTML- og React-koden, og produksjonsbygget ble brukt til å
måle modulstørrelsene. Miljøet har ikke Chrome/Chromium, så DOM, layout og paint
er ikke profilert. Det oppgis derfor ikke konstruerte produksjonstider.

## Dokumentert flaskehals

Ved direkte åpning av `#brl-nok` startet HTML-en valutadata tidlig, men ventet
med `/api/dashboard/summary` til inngangspakken, ruteren og den kode-splittede
valutamodulen var lastet, tolket og montert:

`HTML → inngangspakke (77,54 kB gzip) → valutamodul (5,70 kB gzip) → React-effect → summary-request → komplette investortall`.

Summary-dataene er ikke avhengige av valutaresponsen. Intern navigasjon startet
allerede de to requestene parallelt, noe som bekrefter at rekkefølgen ved direkte
inngang var kunstig. Summary leverer blant annet Bemobi-kurs, eierandel,
aksjeantall, verdi i NOK og NAV-effekt som brukes i de synlige nøkkeltallene og
sensitivitetsberegningen. Uten svaret vises flere av disse som `–` før en ny
render.

Den målbare ekstrakostnaden før endringen var hele nedlastings-, parse- og
monteringstiden for 83,24 kB gzip JavaScript før requesten i det hele tatt kunne
starte. Veggklokketiden avhenger av enheten og nettet. Etter endringen starter
summary-requesten under HTML-parsing, parallelt med kode og det uavhengige
valutakallet. Valutakallet beholder høy prioritet; summary får lav prioritet slik
at supplerende data ikke fortrenger visningens primærdata.

## Kandidater og prioritering

| Kandidat | Startpunkt → sluttpunkt | Tilført tid / mengde | Impact × confidence ÷ risiko | Valg |
| --- | --- | --- | --- | --- |
| Sen summary-request ved direkte BRL/NOK-inngang | HTML → modul/effect → summary-svar → komplette nøkkeltall | Requeststart forsinket av 83,24 kB gzip kode | middels × høy ÷ lav | implementert |
| Sen economic-request på BRL/NOK | Modul/effect → reserveverdi for aksjeantall | Brukes bare som fallback når summary mangler feltet | lav × høy ÷ lav | ikke endret |
| Sen economic-request på Brasil | Modul/effect → NAV-sensitivitet | Primær makrovisning kan vises uten svaret; parallell request kan belaste critical path | lav × middels ÷ middels | ikke endret |
| React/databehandling | API-svar → DOM | Enkle beregninger; de største seriene er memoiserte | lav × middels ÷ middels | ikke endret |
| Backend-latens | Request → svar | Ikke målt i dette miljøet | ukjent × lav ÷ høy | ingen backendendring |

## Korrekthet, caching og feil

Endringen bruker nøyaktig samme URL og eksisterende preload-cache som
`usePollingResource`; den oppretter ikke et nytt dataformat eller en ny
feilhåndteringsvei. React gjør fortsatt statuskontroll, parsing og oppdatering.
Ved feil gjelder eksisterende fallback og feilmelding. Kun starttidspunktet er
flyttet frem. CSP-hashen for inline-scriptet er oppdatert i begge
leveringskonfigurasjonene, uten å åpne for vilkårlige inline-script.

## Før og etter

- **Før:** summary-requesten kunne først starte etter 77,54 kB gzip inngangskode
  og 5,70 kB gzip rutekode, pluss parsing og React-montering.
- **Etter:** requesten opprettes under HTML-parsing. Den kunstige
  modul→data-waterfallen er fjernet, og primærrequesten beholder høy prioritet.
- **Uendret:** Antall nødvendige API-kall, datakorrekthet, caching, polling og
  error handling.

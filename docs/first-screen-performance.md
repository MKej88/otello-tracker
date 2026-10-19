# Lokal måling av første skjerm og API-effektivitet

Fra oktober 2026 registrerer frontend tidsbruk fra navigeringen starter til dataene
først er synlige på de direkte åpnete sidene **Oversikt** og **Brasil**.

## Slik kan resultatene undersøkes

1. Åpne `https://otellotracker.com/#oversikt` i en ny fane.
2. Åpne deretter Datakvalitet → Nettleserytelse.
3. Gjenta for `#brasil`, både med vanlig innlasting og full oppdatering av siden.
4. Sammenlign median og P95 når flere lokale målinger er samlet inn. Vurder de tre
   tregeste same-origin API-stiene opp mot Cloudflare Analytics/Workers-observasjoner.

Dataene ligger bare i nettleserens `localStorage` (maksimalt 40 målinger).
Ingen personidentifikatorer, URL-parametere, eksterne nettadresser eller
måledata sendes til serveren. Lagring kan være utilgjengelig i privat modus.
Dette er **ikke** nettstedomfattende RUM, og tallene må ikke tolkes som aggregert
ytelse for alle besøkende. Spesielt kan små utvalg og cache gi store utslag.

`første synlige data` er en markering etter at React har mottatt og vist
brukbare hoveddata, målt på den opprinnelige hash-ruten med
`requestAnimationFrame`. Den er ikke det samme som LCP, og kan inkludere et
allerede lagret sist-godt datapunkt. TTFB gjelder HTML-dokumentet.
API-varighet er nettleserens komplette ressurstid, ikke kun Worker-CPU-tid.

## Polling

- Skjulte nettleserfaner starter ikke nye periodiske API-oppdateringer.
- Ved aktivering av fanen forsøkes en fersk oppdatering, også etter BFCache.
- Hvis en eldre forespørsel fortsatt pågår, køes én fersk kontroll etterpå.
- Live markedsdata beholder tidligere oppdateringsintervaller.
- Historisk rabatt, tilbakekjøpsstatus og hendelser på oversikten kontrolleres
  hvert 15. minutt mens fanen er aktiv, med oppdatering straks den aktiveres igjen.
- Kjørte forgrunnsforespørsler avbrytes ikke bare fordi fanen skjules;
  API- og NAV-tilstander bevarer derfor siste gode verdi.

Neste steg etter tilstrekkelige målinger er å prioritere målbare flaskehalser.

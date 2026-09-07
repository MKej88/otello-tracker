# Målrettet frontend-audit, 7. september 2026

## Arkitektur og innganger

Frontend er én Vite/React-applikasjon med `main.tsx` som HTML-inngang.
`InvestorApp` viser Oversikt som standard og lazy-laster de elleve øvrige
visningene. Oversikt er den viktigste førsteskjermen og henter seks ressurser med
polling. Fire av dem samles i `/api/dashboard/bootstrap`; rabatt-historikk og
tilbakekjøpsdata ble hentet separat.

## Undersøkte og prioriterte kandidater

| Kandidat | Måling/observasjon | Prioritering |
| --- | --- | --- |
| For stor tilbakekjøpsrespons på Oversikt | Oversikt leste bare `program` og `nav_effect`, men hentet hele dashboardet med prognose, backtest, ukehistorikk og metodebeskrivelse. Reproduserbar fixture: 3 879 byte JSON / 1 430 byte gzip. | Høy sikkerhet, lav kompleksitet, valgt. |
| Bundle og avhengigheter | Produksjonsbygget er 216,89 kB JS / 68,55 kB gzip. React og ReactDOM er eneste produksjonsavhengigheter, og alle sekundærvisninger er allerede splittet. | Ingen trygg materiell endring funnet. |
| Requests og waterfalls | Førsteskjermen starter bootstrap, rabatt-historikk og tilbakekjøp samtidig. Ingen sekvensiell kjede eller duplikat ble funnet. | Ikke endret. |
| Renderarbeid og lister | Oversikt har ingen stor tabell. Polling hindrer overlappende kall. Uten nettleserprofil finnes ikke grunnlag for memo-tiltak. | Ikke endret. |
| Bilder, fonter og layoutskift | Ingen eksterne bilder eller fonter på førsteskjermen; lastetilstander beholder kortstrukturen. | Ikke endret. |

Prioriteringen følger effekt × sikkerhet ÷ kompleksitet/risiko. Det er ikke lagt
inn generell memo-isering eller refaktorering.

## Endring: kompakt respons for tilbakekjøpskortene

**Flaskehals:** Oversikt brukte 2 av 9 toppnivåfelt fra
`/api/buybacks/dashboard`. Nettleseren måtte derfor overføre og tolke data som
først trengs når brukeren åpner den detaljerte tilbakekjøpssiden.

Et nytt endepunkt returnerer nøyaktig de samme `program`- og `nav_effect`-objektene
fra den eksisterende beregningen. Datakorrekthet og feilhåndtering er uendret, og
det detaljerte endepunktet er beholdt urørt.

Samme fixture og kompakte JSON-koding er brukt før og etter:

- Før: **3 879 byte JSON / 1 430 byte gzip**.
- Etter: **379 byte JSON / 239 byte gzip**.
- Reduksjon: **3 500 byte (90,2 %) ukomprimert**, eller **1 191 byte (83,3 %)
  med gzip**.
- Antall førsteskjermrequests er uendret (**3**), men én respons krever vesentlig
  mindre overføring og parsing.

Bundle-størrelsen påvirkes ikke på en meningsfull måte. LCP, INP og CLS kunne ikke
måles fordi miljøet ikke har Chrome/Chromium. Endringen retter derfor bare den
flaskehalsen som kunne dokumenteres reproducerbart.

## Resultat

- **Viktigste flaskehals før:** tilbakekjøpskortene lastet et helt detaljdatasett
  selv om førsteskjermen bare bruker to feltgrupper.
- **Endringer gjort:** et kompatibelt, kompakt statusendepunkt i begge Python-
  kjøremiljøene, brukt av Oversikt.
- **Måling før:** 3 879 byte JSON / 1 430 byte gzip.
- **Måling etter:** 379 byte JSON / 239 byte gzip.
- **Forbedring:** 90,2 % mindre ukomprimert respons og 83,3 % mindre med gzip.
- **Trade-offs:** serveren utfører foreløpig samme beregning; gevinsten gjelder
  nettverk og arbeid i nettleseren, ikke beregningstid på serveren.
- **Neste mest lovende forbedring:** mål LCP og main-thread-tid i en ekte mobil-
  nettleser før eventuell videre splitting av Oversikt eller React-optimalisering.

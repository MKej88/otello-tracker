# Undersøkelse av frontendens critical path (2026-09-25)

## Metode

Gjennomgangen fulgte direkte åpning og intern navigasjon gjennom ruting,
modulinnlasting, API-kall, state, React-rendering og nettleserarbeid. Koden ble
kontrollert for requestrekkefølge og faktisk bruk av hvert svar. Et
produksjonsbygg ble brukt til å måle modulstørrelsene. Reelle Worker- og
paint-tider kan ikke måles representativt i dette lokale miljøet.

## Dokumentert flaskehals

Ved navigasjon til **Tilbakekjøpsprogram** startet frontend to uavhengige kall:
`/api/buybacks/dashboard` og `/api/bemobi/dashboard`. Det første svaret bygger
hele visningen. Bemobi-svaret ble lagret i state, og en verdi ble beregnet, men
verdien ble aldri lest av renderingen. Kallet ble dessuten gjentatt hvert 30.
minutt.

Critical path var derfor:

`klikk → modul og to API-kall → unødvendig parsing/state-oppdatering/render`.

Det ubrukte kallet blokkerte ikke hovedsvaret med en `await`, men konkurrerte om
nettverk, Worker- og databasekapasitet akkurat når det nyttige kallet skulle
gjøre siden klar. Før endringen startet to datakall ved hver navigasjon og ett
unødvendig kall per 30 minutter mens siden sto åpen. Etter endringen starter kun
det ene kallet som visningen bruker. Produksjonsbygget viser at inngangsbunten er
77,66 kB gzip og tilbakekjøpsmodulen 4,28 kB gzip; dette var ikke en
modul→request-waterfall fordi kode og data allerede startet parallelt.
Etter at den døde request- og state-koden ble fjernet, er tilbakekjøpsmodulen
4,18 kB gzip med samme byggemetode.

## Kandidater og prioritering

| Kandidat | Startpunkt → sluttpunkt | Tilført tid / mengde | Impact × confidence ÷ risiko | Valg |
| --- | --- | --- | --- | --- |
| Ubrukt Bemobi-request på tilbakekjøpssiden | navigasjon → request/parsing → ubrukt state/render | Ett API-kall per navigasjon og per 30 minutt; ingen synlig verdi | middels × svært høy ÷ svært lav | implementert |
| Modulinnlasting ved navigasjon | klikk → kode-splittet modul → render | 4,28 kB gzip for valgt visning | lav × høy ÷ middels | ikke endret |
| Hovedkallet for tilbakekjøpsdata | request → korrekt innhold | faktisk produksjonslatens er ikke målt lokalt | ukjent × lav ÷ høy | ikke endret |
| React/DOM/layout/paint | state → synlig visning | ingen tung behandling eller målt langoppgave dokumentert | lav × middels ÷ middels | ikke endret |

## Avhengighet, korrekthet og feil

Det var ingen reell avhengighet mellom svarene. Tvert imot viste den statiske
bruksanalysen at Bemobi-dataene ikke nådde DOM-en i det hele tatt. Derfor ble
kallet fjernet i stedet for å parallelliseres på nytt. Endringen berører ikke
tilbakekjøpssvarets caching, polling eller feilhåndtering. Den fjerner bare død
state og et ubrukt requestløp.

## Før og etter

- **Før:** to API-kall ved navigasjon, der ett svar ikke påvirket innholdet, og
  en ubrukt Bemobi-oppdatering hvert 30. minutt.
- **Etter:** ett nødvendig API-kall ved navigasjon og ingen ubrukt periodisk
  request eller state-oppdatering.
- **Forventet brukergevinst:** mindre konkurranse om nettverk og backend når
  hoveddataene lastes, særlig på treg forbindelse eller ved Worker-oppstart.
- **Uendret:** synlig innhold, datakorrekthet, caching og feilhåndtering for
  tilbakekjøpsdataene.

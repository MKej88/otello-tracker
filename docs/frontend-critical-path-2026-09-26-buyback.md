# Undersøkelse av critical path – tilbakekjøpsvisningen (2026-09-26)

## Metode

Gjennomgangen fulgte klikk og direkte åpning via ruting, modulinnlasting og
`/api/buybacks/dashboard`, videre gjennom databasearbeidet, state, React-rendering
og synlig innhold. Produksjonsbygget og en deterministisk samtidighetstest ble
brukt. Reell Cloudflare-latens og nettleserens layout/paint kan ikke måles
representativt i dette lokale miljøet.

## Dokumentert flaskehals

Frontend starter rutemodulen og API-kallet parallelt og gjenbruker pågående kall.
Inne i API-et ventet derimot tre uavhengige D1-lesinger etter hverandre etter at
prognosen hadde bestemt datoen:

`prognose → siste tilbakekjøp → aksjeantall → NAV-snapshot → respons → React`.

Alle tre spørringene trenger datoen, men ingen trenger resultatet fra en av de
andre. Den serielle delen la derfor til summen av tre databaseventinger. Med 30 ms
per D1-runde er denne delen 90 ms før endringen og omtrent 30 ms etter, altså om
lag 60 ms eller 67 % kortere. Dette er en kontrollert ventemodell, ikke en påstand
om produksjonslatens. Samtidighetstesten verifiserer at alle tre lesingene nå er
startet før noen av dem får fullføre.

## Kandidater og prioritering

| Kandidat | Startpunkt → sluttpunkt | Tilført tid | Impact × confidence ÷ risiko | Valg |
| --- | --- | --- | --- | --- |
| Tre serielle, uavhengige D1-lesinger | prognose ferdig → grunnlagsdata klare | to unødvendige D1-ventebølger; ca. 60 ms i 30 ms-modellen | høy × høy ÷ lav | implementert |
| Prognosen før grunnlagslesingene | API-start → prognose ferdig | datoen kommer fra prognosen og brukes av alle tre spørringene | middels × høy ÷ høy | beholdt; avhengigheten er reell |
| Rutemodul | klikk → modul klar | 4,17 kB gzip | lav × høy ÷ middels | beholdt; data starter allerede parallelt |
| React og klientberegning | svar → DOM/paint | små, memoiserte lister; ingen målt langoppgave | lav × middels ÷ middels | ikke endret |

## Korrekthet og feil

Spørringene, parameterne og responsformatet er uendret. `asyncio.gather` returnerer
resultatene i samme faste rekkefølge og sender databasefeil videre til eksisterende
API-feilhåndtering. Ingen cache, fallback eller frontend-state er endret. Den eneste
avveiningen er opptil tre samtidige D1-lesinger i stedet for én om gangen; antallet
spørringer er det samme.

## Før og etter

- **Før:** tre databaseventebølger etter prognosen.
- **Etter:** én databaseventebølge for de samme tre lesingene.
- **Forventet brukergevinst:** API-svaret og dermed korrekt tilbakekjøpsinnhold kan
  bli klart omtrent to D1-rundturer tidligere.
- **Uendret:** datagrunnlag, beregninger, caching, feilbehandling og rendering.

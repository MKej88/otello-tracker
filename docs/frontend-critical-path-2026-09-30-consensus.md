# Undersøkelse av critical path – konsensusvisningen (2026-09-30)

## Metode

Gjennomgangen fulgte direkte åpning og intern navigasjon via ruting,
modulinnlasting, `/api/bemobi/consensus`, databasearbeid, state og React-rendering
til nyttig konsensusinnhold er synlig. Produksjonsbygget og en deterministisk
samtidighetstest ble brukt. Reell Cloudflare-latens og nettleserens layout/paint
kan ikke måles representativt i dette lokale miljøet.

## Dokumentert flaskehals

Frontend starter både den kode-splittede modulen og API-kallet før ruten monteres,
og komponenten gjenbruker den pågående requesten. Etter at Bemobi-grunnlaget var
klart, ventet API-et likevel på fem uavhengige databaselesinger etter hverandre:

`brukerhandling → modul + request → Bemobi-grunnlag → 5 × databaseventing → respons → React`.

Lesingene henter analytikere, fremoverskuende estimater, historiske avvik, neste
kvartal og referansemodell. Ingen av dem bruker resultatet fra en annen. Med en
illustrativ D1-rundtur på 20 ms kostet denne delen derfor omtrent 100 ms før og
20 ms etter endringen: rundt 80 ms, eller 80 %, kortere. Dette er en kontrollert
ventemodell, ikke en påstand om produksjonslatens. Samtidighetstesten verifiserer
at alle fem operasjonene er startet før noen får fullføre.

## Kandidater og prioritering

| Kandidat | Startpunkt → sluttpunkt | Tilført tid | Impact × confidence ÷ risiko | Valg |
| --- | --- | --- | --- | --- |
| Fem serielle, uavhengige faktalesinger | Bemobi-grunnlag klart → konsensusgrunnlag klart | Fire unødvendige D1-ventebølger; ca. 80 ms i 20 ms-modellen | høy × svært høy ÷ lav | implementert |
| Bemobi-grunnlaget må fullføres først | API-start → faktalesinger | Påfølgende beregninger trenger markedspris og aksjeantall fra Bemobi-svaret | middels × høy ÷ høy | beholdt; avhengigheten er reell |
| Kode-splittet modul | navigasjon → modul klar | 5,00 kB gzip i lokalt produksjonsbygg | lav × høy ÷ middels | beholdt; API-kallet starter allerede parallelt |
| React, databehandling og DOM | API-svar → synlig innhold | Små, lineære datasett uten dokumentert langoppgave | lav × middels ÷ middels | ikke endret |

## Korrekthet og feil

De samme fem funksjonene kalles med samme argumenter, og resultatene pakkes ut i
samme faste rekkefølge før eksisterende filtrering og validering. Antall
databasekall, responsformat og frontend-cache er uendret. `asyncio.gather` sender
fortsatt databasefeil videre til eksisterende API-feilhåndtering; feil skjules
ikke.

## Før og etter

- **Før:** fem databaseventebølger etter det nødvendige Bemobi-grunnlaget.
- **Etter:** én databaseventebølge for de samme fem lesingene.
- **Forventet brukergevinst:** korrekt konsensusinnhold kan bli klart omtrent fire
  D1-rundturer tidligere.
- **Uendret:** datagrunnlag, beregninger, caching, validering og rendering.

# Undersøkelse av frontendens critical path – Bemobi (2026-09-26)

## Metode

Gjennomgangen fulgte direkte åpning og intern navigasjon til Bemobi fra
brukerhandling, ruting og modulinnlasting, via API-kall og backendarbeid, til
state, React-rendering og synlig innhold. Requestrekkefølgen ble kontrollert i
HTML-en, ruteren, komponenten og `/api/bemobi/dashboard`. Produksjonsbygget og
relevante Python-tester ble kjørt lokalt. Miljøet har ikke Chrome/Chromium eller
en representativ produksjonsdatabase, så reell nettverks-, layout- og
paint-tid er ikke målt.

## Dokumentert flaskehals

Frontend startet modul, Bemobi-data og konsensus parallelt. Bemobi-komponenten
gjenbrukte den pågående requesten, slik at det ikke oppsto et duplikat. Inne i
`/api/bemobi/dashboard` lå derimot sju uavhengige databaselesinger i serie etter
at NAV-sammendraget var klart:

`brukerhandling → modul + request → NAV-sammendrag → 7 × databaseventing → JSON → state → render`.

Lesingene henter siste utdeling, resultatkilde og fem separate grupper av
Bemobi-fakta. Ingen av de sju bruker resultatet fra en annen. Den serielle
avhengigheten var derfor ikke reell.

Et kontrollert testscenario som holder hver lesing igjen til alle sju er
startet dokumenterer at de nå overlapper. Med en illustrativ ventetid på 20 ms
per D1-operasjon reduseres denne delen av critical path fra omtrent 140 ms til
omtrent 20 ms, altså rundt 120 ms tidligere svar. Dette er et estimat av den
fjernede køtiden, ikke en påstand om produksjonslatens. Databehandling etter
lesingene er små, lineære operasjoner, og responsen vises med én state-oppdatering.

## Kandidater og prioritering

| Kandidat | Startpunkt → sluttpunkt | Tilført tid / mengde | Impact × confidence ÷ risiko | Valg |
| --- | --- | --- | --- | --- |
| Sju serielle, uavhengige D1-lesinger | ferdig NAV-sammendrag → alle Bemobi-fakta klare | seks unødvendige ventetrinn; ca. 120 ms ved 20 ms per lesing | høy × svært høy ÷ lav | implementert |
| Kode-splittet Bemobi-modul | klikk → modul → render | liten rutemodul og lastes parallelt med data | lav × høy ÷ middels | ikke endret |
| Konsensus-request | navigasjon → supplerende konsensus | brukes i samme visning, men blokkerer ikke hoveddata | lav × høy ÷ middels | ikke endret |
| React, DOM og databehandling | API-svar → synlig innhold | ingen dokumentert langoppgave eller request-waterfall | lav × middels ÷ middels | ikke endret |

## Før og etter

- **Før:** De sju uavhengige lesingene ventet på hverandre, og total ventetid
  var summen av alle sju.
- **Etter:** Alle sju starter samtidig etter det nødvendige NAV-sammendraget;
  ventetiden bestemmes av den tregeste lesingen.
- **Korrekthet:** De samme funksjonene, argumentene og returverdiene brukes.
  Resultatene pakkes ut i samme rekkefølge, og validering og responsformat er
  uendret.
- **Feilhåndtering:** En databasefeil avbryter fortsatt requesten og blir ikke
  skjult. Dette er dekket av en egen test.
- **Caching:** Frontendens requestgjenbruk, navigasjonscache og polling er
  uendret.

# Undersøkelse av frontendens critical path – Cash (2026-09-26)

## Metode

Gjennomgangen fulgte direkte åpning og intern navigasjon til Cash fra klikk og
ruting, via kode- og datainnlasting, til state, React-rendering og synlig
innhold. Requestrekkefølgen og den faktiske bruken av svarene ble kontrollert i
ruteren og Cash-komponenten. Produksjonsbygget ble kjørt før og etter med samme
kommando. Miljøet har ikke Chrome/Chromium eller en representativ produksjons-
database, så reell Worker-latens, layout og paint er ikke målt lokalt.

## Dokumentert flaskehals

Cash-ruten startet de tre uavhengige kjernekallene parallelt, men komponenten
ventet på `Promise.allSettled` før **noen** av svarene ble lagt i React-state.
Deretter krevde renderingen fortsatt alle tre svar før den viste annet enn en
lastemelding:

`klikk → modul + tre parallelle requests → tregeste svar → tre state-oppdateringer → nyttig innhold`.

`/api/dashboard/economic` inneholder Otellos estimerte kontantbeholdning alene.
Denne verdien er korrekt og nyttig uten `/api/bemobi/dashboard` eller
`/api/dashboard/summary`. Avhengigheten var derfor ikke reell for det første
nyttige innholdet; den gjelder bare den komplette analysen som kombinerer
Otello-cash, Bemobi-cash, NAV og markedskurs.

Den kunstige ventetiden var forskjellen mellom svartiden til economic-kallet og
det tregeste av de tre kallene. Eksempel med kontrollerte responstider på 200 ms,
400 ms og 1 200 ms: før ble første tall synlig etter omtrent 1 200 ms; etter kan
Otello-cash vises etter omtrent 200 ms, altså rundt 1 000 ms tidligere. Dette er
en illustrasjon av kødannelsen, ikke en påstand om produksjonslatens.

## Kandidater og prioritering

| Kandidat | Startpunkt → sluttpunkt | Tilført tid / mengde | Impact × confidence ÷ risiko | Valg |
| --- | --- | --- | --- | --- |
| State blokkert av tregeste Cash-svar | første ferdige svar → `allSettled` → første nyttige tall | forskjellen mellom economic og tregeste svar; opptil 1 000 ms i kontrollert eksempel | høy × høy ÷ lav | implementert |
| Fire parallelle Cash-kall | navigasjon → nettverk/Worker → komplett analyse | tre kjernekall og ett supplerende kall; alle feltene brukes | middels × høy ÷ høy | ikke endret |
| Kode-splittet Cash-modul | klikk → modul → render | 6,31 kB gzip etter endringen | lav × høy ÷ middels | ikke endret |
| Databehandling og React | svar → beregninger → DOM | beregningene er lineære og memoiserte; ingen dokumentert langoppgave | lav × middels ÷ middels | ikke endret |
| Backend-latens | request → response | ikke representativt målbar lokalt | ukjent × lav ÷ høy | ingen backendendring |

## Før og etter

- **Før:** Alle tre uavhengige svar måtte være ferdige før det første ble lagt i
  state, og siden viste bare en generell lastemelding frem til tregeste svar.
- **Etter:** Hvert svar publiseres når det kommer. Når economic er først, vises
  estimert Otello-cash med dato mens de øvrige dataene fortsatt lastes.
- **Komplett visning:** Den eksisterende komplette analysen vises fortsatt først
  når alle tre kjerneresponsene finnes. Formler og datakilder er uendret.
- **Feil og caching:** De samme requestene, navigasjonscachen og
  `Promise.allSettled`-baserte feilvurderingen beholdes. En delvis respons blir
  ikke presentert som en komplett analyse.
- **Bygg:** Cash-modulen er 24,38 kB / 6,31 kB gzip. Endringen er rettet mot
  ventetid til nyttig innhold, ikke en syntetisk reduksjon i buntstørrelse.

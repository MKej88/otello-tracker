# Målrettet frontend-audit – oppfølging 11. oktober 2026

Én produksjonsendring beholdes: gjenbruk av tallformat i `src/uiFormat.ts`.
Cash-kalkulatorens input krevde gjentatt opprettelse av norsk tallformat under
hver render. Fem lokale Chromium-prøver viser 24,1 % mindre main-thread-arbeid
og 33,3 % kortere tid fra tastetrykk til neste visning. Ingen sikker gevinst i
første innlasting er dokumentert.

Dette er en **ny baseline på commit `29582e8`**, ikke en gjentakelse av gevinstene
i `frontend-performance-audit-2026-10-11.md`. Den tidligere auditens endringer
i NAV-sensitivitet og innlasting av Oversikt var allerede på plass. Arbeidsmappen
var ren ved start; målingene ble utført på branch `work` før PR-opprettelse.

## Arkitektur og inngangspunkter

- `index.html` starter rutespesifikke API-preloads under HTML-parsing.
- `main.tsx` monterer React 19 / `InvestorApp`. Hashen velger mellom tolv sider.
  Oversikt importeres direkte; de elleve andre sidene bruker dynamiske imports.
- Vite bygger statiske assets. Produksjon bruker Cloudflare Worker/Python/D1;
  nginx og Python-backend er også tilgjengelige som referanselevering.
- `navigationDataPreload.ts` samler pågående requests og gjenbruker svar i 30 s.
  Navigasjon starter kode og data parallelt; hover-preload venter på 120 ms intensjon.
- Oversikt samler fem ressurser i bootstrap, med sist-gode klientcache, umiddelbar
  revalidering og 750 ms fallback. `usePollingResource` håndterer polling og resume.
- Cash publiserer uavhengige svar separat. NAV prioriterer valgt periode før
  bakgrunnsbunten. Historikk ber normalt om maksimalt 72 punkter per periode.
- Legacy `App.tsx` og `HistoryPage.tsx` er ikke aktive inngangspunkter.

| Hash / side | Viktigste data |
| --- | --- |
| tom / `#oversikt` | Bootstrap, ett års rabatt-historikk, Bemobi etter Oslo-close |
| `#nav` | Economic, buyback, valgt rabattperiode og perioder i bakgrunn |
| `#nav-sensitivitet` | Summary og economic; lokale scenarier |
| `#historikk` | Economic og rabatt-historikk |
| `#tilbakekjop` | Buyback-dashboard |
| `#cash` | Summary, Bemobi-dashboard, economic, buyback-dashboard |
| `#bemobi` | Bemobi-dashboard og consensus |
| `#brl-nok` | FX-dashboard og summary |
| `#brasil` | Brazil-dashboard og economic |
| `#konsensus` | Bemobi-consensus |
| `#nyheter` | News-events |
| `#datakvalitet` | Runtime-status, report-status, source-status |

## Metode og avgrensning

Endelige før/etter-prøver bruker Node 22.23.3, prosjektets låste avhengigheter,
Vite 8.3.2 og Chromium 151.0.7922.173. Miljøet startet med Node 24 og Vite 8.3.1;
innledende utforskning ble kjørt der, men inngår ikke i før/etter-tabellen.
Node 22 ble installert separat i `/tmp`; ingen package- eller lockfiler er endret.

API-grunnlaget genereres med repoets `build_worker_runtime_fixture.py` i en separat
database (`/tmp/perf-audit.db`, fixture-dato 14. august 2026). Lokal HTTP-replay
serverer production-assets og disse svarene med gzip og fast 80 ms forsinkelse.
Cash bruker alle fire faktiske fixture-payloads. For Oversikt settes bootstrap
sammen av fixture-svarene, med tom hendelsesliste; etter-Oslo-ressursen returnerer
`ready: false`. NAV-bakgrunnsbunten bruker samme korte fixturehistorikk for
periodene. Dette er ikke representativt for store produksjonspayloads eller
beregningskostnad i Worker/D1, og brukes ikke til å hevde produksjonslatens.

Målingen bruker 1440 × 1200 vindu, 4× CPU-struping og ingen båndbreddestruping.
Hver kald prøve går via `about:blank`, tømt HTTP-cache og tømt localStorage.
LCP/FCP/CLS leses via nettleserens Performance API. Overføring og requestantall
bruker Resource Timing, uten hoveddokumentet. Siden får 2,2 s til å laste før
innlastingsresultatet leses.

Inputprøven fokuserer Cash-sidens første range-input og sender 30 vekslende
ArrowRight/ArrowLeft-tastetrykk via CDP. Main-thread/JavaScript er differansene
i CDP `TaskDuration`/`ScriptDuration`. Tastetrykk til neste visning måles til to
`requestAnimationFrame`-callbacks og inkluderer verktøytransport og frame-venting.
Dette er **ikke feltmålt INP**. Fem prøver per variant; tabellen bruker medianen
av prøvenes totaler og medianer. Ingen formatteringsteller eller CPU-profiler
kjører under disse fem før/etter-prøvene.

Separat utforskende instrumentering registrerte 2 130 `Number.toLocaleString`-
kall og 158,2 ms i disse kallene ved 30 justeringer. En separat CPU-profil av den
endelige baselinen peker på den minifiserte `formatNumber` i inngangspakken.
Det bekrefter at kostnaden ligger på den faktiske inputstien, ikke bare i en
isolert mikrobenchmark. `formatInteger` og lokal formatering i andre sider er
ikke endret.

Prøveresultater er lagret i `frontend-performance-audit-2026-10-11-followup.json`.
Komplette lokale rådata, CPU-profil, replay-, måle- og snapshot-skript ligger i
`/workspace/scratch/otello-performance-audit/`. Skriptene krever Chromium med
lokale sockets. Måleskriptets `ROUTES=cash,oversikt RUNS=5` kjører hovedprøven;
`COUNT=1` og `PROFILE=1` er separate diagnosemoduser. Replay-skriptet peker på
`frontend/dist` og `/tmp/perf-audit-payloads` fra fixture-generatoren.

## Kandidater, rangert etter impact × confidence ÷ kompleksitet/risiko

| Kandidat | Dokumentasjon | Beslutning |
| --- | --- | --- |
| Gjentatt tallformatopprettelse på Cash-input | 71 locale-kall per justering; CPU-profil og uinstrumentert før/etter viser materiell kostnad | Høy impact på input × høy confidence ÷ svært lav kompleksitet. **Valgt.** |
| Tidlig standardkode på andre ruter | Inngangs-JS 256,47 kB / 80,17 kB gzip; Oversikt inngår også på direkte andre ruter | Potensial, men tidligere audit viser avveining mellom Oversikt og øvrige ruter. Ingen ny endring uten rutespesifikk båndbreddekontroll. |
| Requests, waterfalls, payloads og refetch | Seks utforskede ruter: Oversikt 3, NAV 4, Cash 4, Bemobi 2, Konsensus 1, sensitivitet 2 faktiske API-kall; ingen duplikater i prøvevinduet | Eksisterende parallellisering og deduplisering fungerer. Produksjonslatens og full pollingperiode er ikke målt. Ingen cache- eller API-endring. |
| Renderfrekvens, effects og beregninger | Cash rerendrer på input; målt tung funksjon er formatering. Page-update har stabile primitive effect-avhengigheter | Ingen separat render-count-måling eller dokumentert behov for React.memo/useMemo/useCallback. Ingen slik endring. |
| Dependencies og splitting | Bare React/ReactDOM i runtime; øvrige visninger splittes allerede | Ingen stor unødvendig runtime-avhengighet identifisert. Ingen arkitekturendring. |
| Store lister og main thread | 187–528 DOM-elementer i de seks fixture-visningene; nyhetslisten starter med ti elementer, historikk begrenses | Fixture har bare to historikkpunkter. Virtualisering og bredere beregningsendringer er ikke begrunnet av disse prøvene. |
| Bilder, fonter, layout og asset-cache | Liten lokal logo med dimensjoner, systemfonter, immutable-cache for hashede assets og nginx-gzip | Ingen materiell assetflaskehals identifisert. CLS uendret i før/etter. |
| Navigasjon og ferske data | Eksisterende 30 s requestcache og bootstrap-revalidering; navigasjonssnapshots og eksisterende fallback/resume-tester består | Ingen ny trygg ytelsesgevinst dokumentert. Freshness-policy beholdes. |

## Endring og før/etter

`frontend/src/uiFormat.ts` gjenbruker nå en `Intl.NumberFormat` per presisjon
via en modul-lokal Map, opprettet ved første bruk. Cash brukte samme locale og
options på nytt for hvert tall i hver render. Gjenbruk unngår formatopprettelsen
mens selve tallene fortsatt formateres på nytt. Beregning, avrunding, norske
minustegn/tusenskiller og håndtering av manglende/ugyldige tall beholdes.

| Mål | Før | Etter | Endring |
| --- | ---: | ---: | ---: |
| Cash: main-thread, 30 justeringer | 703,20 ms | 533,48 ms | **−24,1 %** |
| Cash: JavaScript, 30 justeringer | 297,61 ms | 151,66 ms | **−49,0 %** |
| Cash: tastetrykk → neste visning | 47,95 ms | 32,00 ms | **−33,3 %** |
| Cash LCP | 928 ms | 936 ms | +8 ms |
| Cash FCP | 460 ms | 468 ms | +8 ms |
| Cash CLS | 0,018623 | 0,018623 | Uendret |
| Cash ressursrequests / API-requests | 12 / 4 | 12 / 4 | Uendret |
| Cash overføring | 118 080 B | 118 107 B | +27 B |
| Oversikt LCP / FCP | 604 / 604 ms | 580 / 580 ms | −24 ms |
| Oversikt CLS | 0,013396 | 0,013396 | Uendret |
| Oversikt ressursrequests / API-requests | 8 / 3 | 8 / 3 | Uendret |
| Oversikt overføring | 105 955 B | 105 982 B | +27 B |

Forskjellene i LCP/FCP er små i fem lokale prøver og gir ikke grunnlag for å
hevde bedre innlastingshastighet. Input er det dokumenterte resultatet:
prøvenes medianer var 47,45–48,70 ms før og 31,85–32,15 ms etter. Main-thread
var 658–778 ms før og 420–568 ms etter. Dette er labresultater, ikke RUM.

Inngangs-JS øker med 77 ukomprimerte bytes og 27 gzip-bytes (Python gzip nivå 9,
samme metode før/etter: 79 195 → 79 222 B). Noen få formatterobjekter beholdes
mens modulen er lastet. Ingen dataverdier caches. Ingen ny dependency.

## Funksjonalitet og kontroll

- `npm run build`: bestått med Node 22 og Vite 8.3.2, inkludert TypeScript.
- `npm test`: 13 frontend-testfiler bestått, inkludert alle tolv eksisterende.
- Ny `tools/uiFormat.test.ts`: eksplisitt norsk visning og ugyldige verdier;
  12 066 paritetssammenligninger mot tidligere formattering, inkludert skiftende
  presisjon, minus null, avrundingsgrenser og svært små/store tall.
- 49 relevante Python-tester bestått: `backend/tests/*frontend*.py`,
  `test_first_load_performance_contract.py`, `test_overview_no_blocking_calendar.py`.
- 15 nettlesersnapshots er identiske før/etter: hele hovedinnholdets tekst,
  inputverdier/grenser og aria-labels. Omfatter begge Cash-skyveknappenes Home,
  End og piltaster, 390 px mobil og navigasjon via Oversikt, NAV, Bemobi,
  Konsensus og tilbake til Cash. Kalkulatoren viser også null kjøp over makspris.
- `git diff --check`: bestått. Frontend har ikke lint-script eller frontend-linter;
  ingen ny lintavhengighet er lagt til.
- Full produksjons-/Worker-smoke og feltmålt INP er ikke kjørt. Den eksisterende
  brede `browser-smoke.mjs` bruker eldre Oversikt-selectorer; her brukes den
  avgrensede før/etter-kontrollen med dagens komponenter.

## Resultat

- **Viktigste flaskehals før:** gjentatt tallformatopprettelse ved Cash-input.
- **Endringer gjort:** én liten endring i delt tallformat, med paritetstest.
- **Måling før:** 703,20 ms main-thread per 30 justeringer; 47,95 ms til visning.
- **Måling etter:** 533,48 ms; 32,00 ms.
- **Forbedring:** 24,1 % mindre main-thread-arbeid og 33,3 % raskere inputvisning.
- **Trade-offs:** 27 ekstra gzip-bytes og noen få formatterobjekter; ingen sikker
  forbedring i LCP/FCP, requestantall eller CLS.
- **Neste mest lovende forbedring:** mål bootstrap-/D1-latens og rutefordeling
  med produksjonsdata, deretter prøv tidlig rutespesifikk moduloppdagelse for å
  redusere standardkodens kostnad på direkte undersider uten å forsinke Oversikt.

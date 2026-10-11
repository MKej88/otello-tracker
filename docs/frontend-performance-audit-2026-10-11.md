# Målrettet frontend-audit – 11. oktober 2026

To kodeendringer beholdes: gjenbruk av tallformat i NAV-sensitivitet og direkte
import av standardvisningen Oversikt. Begge er kontrollert i et faktisk
production-build i Chromium. Ingen dependencies, beregninger, API-kontrakter,
cachelevetider eller feilhåndtering er endret.

## Arkitektur og inngangspunkter

`frontend/index.html` starter rutespesifikke API-preloads under HTML-parsing.
`src/main.tsx` monterer React 19 / `InvestorApp`; Vite 8 bygger statiske assets.
Navigasjon skjer med URL-hash, og sidene lastes via dynamiske imports. Produksjon
bruker Cloudflare Worker, Python-API og D1. Lokal Python-backend er en referanse,
ikke en full kopi av produksjonsmiljøet.

| Visning / hash | Sentrale data ved inngang |
| --- | --- |
| Oversikt / tom hash, `#oversikt` | Bootstrap (summary, economic, quotes, buyback, events), ett års rabatt-historikk; separat Bemobi etter Oslo-close |
| NAV / `#nav` | Economic, buyback-dashboard, synlig 1 M-historikk; øvrige perioder i bakgrunnsbunt |
| NAV-sensitivitet / `#nav-sensitivitet` | Summary og economic; lokal scenarioberegning |
| Historikk / `#historikk` | Rabatt-historikk og economic |
| Tilbakekjøp / `#tilbakekjop` | Buyback-dashboard |
| Cash / `#cash` | Summary, Bemobi-dashboard, economic og valgfritt buyback-grunnlag |
| Bemobi / `#bemobi` | Bemobi-dashboard og consensus |
| BRL/NOK / `#brl-nok` | FX-dashboard og summary |
| Brasil / `#brasil` | Brazil-dashboard og economic |
| Konsensus / `#konsensus` | Bemobi-consensus |
| Nyheter / `#nyheter` | News-events |
| Datakvalitet / `#datakvalitet` | Runtime-status, report-status og Bemobi-source-status |

`navigationDataPreload.ts` dedupliserer pågående URL-requests og gjenbruker svar i
30 sekunder. `usePollingResource.ts` holder senere polling separat og henter ferske
data ved gjenopptatt sidebruk. Bootstrap har sist-gode klientcache og umiddelbar
nettverksrevalidering, med en 750 ms sikret fallback. Datastatus bruker tidspunkter
fra sidens datagrunnlag. Diagnostikk er ikke globalt montert. Legacy `App.tsx` og
`HistoryPage.tsx` er ikke aktive inngangspunkter.

## Målemetode og begrensninger

- Baseline: commit `2997efa`, ren arbeidsmappe ved oppgavestart, eksisterende branch `work`.
- Node 22.23.3 fra miljøets eksisterende installasjon; `npm run build` og `npm test`.
- Headless Chromium, production-assets, 1440 × 1200 og 4× CPU-struping.
- API-payloads genereres med repoets eksisterende `build_worker_runtime_fixture.py`
  i en separat database. Fixture-dato er 14. august 2026. Ingen produksjonsdata endres.
- Lokal replay-server gzip-komprimerer svar og legger til identisk 80 ms svartid.
  Hashede assets har immutable-cache; API-svar revalideres. Dette modellerer
  requestfaser, ikke faktisk Cloudflare-, D1- eller internettlatens.
- Fem kalde innlastinger før, etter bare tallformatendringen, og etter begge
  endringene. Hver innlasting går via et tomt dokument med tømt HTTP-cache og
  localStorage, slik at hash-navigasjon ikke feilaktig telles som en kald innlasting.
- LCP, FCP og CLS leses med PerformanceObserver. Requests og overføring leses med
  Resource Timing (`transferSize`, inkludert nettleserens estimerte headerkostnad).
- Inputprøven sender 20 reelle tastetrykk via CDP til scenariofeltet. Main-thread-tid
  er differansen i CDP `TaskDuration`; tastetrykk til neste visning måles til to
  `requestAnimationFrame`-callbacks. Dette inkluderer visningssynkronisering og
  verktøytransport; det er **ikke feltmålt INP**.
- Først telles og tidsmåles `Number.toLocaleString`, og CPU-profil tas. Deretter
  gjentas før/etter i tre serier uten denne tellerinstrumenteringen. De sistnevnte
  tallene brukes som hovedresultat for input, slik at tellerarbeid ikke fremstilles
  som produktgevinst.
- En ekstra kontroll bruker 1,6 Mbit/s nedlasting, samme 80 ms serverforsinkelse og
  CPU-struping, tre kalde innlastinger per variant.
- Alle resultater er medianer. Små prøveantall og CPU-variasjon gjør tallene til
  lokale laboratorieresultater. Ingen Lighthouse-score brukes som beslutningsgrunnlag.
- Oversikt og NAV-sensitivitet er tidsprofilert. Øvrige sider er kartlagt i kildekoden;
  fixture inneholder blant annet bare to historikkpunkter og ingen full Brasil-/FX-
  eller produksjonsstatuspayload. Store produksjonspayloads og alle sidene er derfor
  ikke fullstendig ytelsesprofilert. Produksjons-RUM, API-latens, full Worker-smoke
  og autentisert produksjonsnavigasjon er ikke målt i dette miljøet.

## Kandidater og prioritering

Rangeringen følger impact × confidence ÷ kompleksitet/risiko. Vurderingene gjelder
målt lokal atferd og konkret kodegrunnlag, ikke antatt produksjonstrafikk.

| Kandidat | Funn / måling | Prioritet og beslutning |
| --- | --- | --- |
| Gjentatt tallformatopprettelse ved input | 281 formatteringer per tastetrykk, 5 620 for 20 tastetrykk; ca. 243 ms i formattering i instrumentert median. CPU-profil viser samme kall på den aktive stien. | Høy impact × høy confidence ÷ svært lav risiko. **Valgt.** |
| Sen oppdagelse av Oversikt-modulen | Bootstrap er ferdig rundt 244 ms i første baseline-prøve; Oversikt og fire nødvendige støtteressurser starter først rundt 327–330 ms og er ferdige rundt 421–426 ms. | Høy lokal impact × høy confidence ÷ lav/moderat risiko på andre ruter. **Valgt etter båndbreddekontroll.** |
| React-state/effect-kjeder og renderfrekvens | Input rendrer matrisen på nytt, men den dokumenterte kostnaden ligger i formatopprettelse. Polling-callbacks er stabile; page-update-effekter har stabile primitive avhengigheter. | Ingen egen renderoptimalisering: ingen nye useMemo/useCallback/React.memo. |
| Bundle og dependencies | Bare React/ReactDOM som runtime-dependencies. Produksjonsmoduler er omtrent 6–26 kB ukomprimert; sidene er allerede splittet. | Ingen klart dokumentert trygg gevinst ved avhengighetsbytte eller generell splitting. |
| Sekvensielle/dupliserte requests og refetch | Oversikt: 3 faktiske API-requests; direkte sensitivitet: 2. Preloads gjenbrukes. Cash starter uavhengige svar parallelt og publiserer dem separat. NAV prioriterer valgt periode før bakgrunnsbunt. | Ingen ny materiell duplikat/waterfall dokumentert utover standardvisningens modulinnlasting. |
| Store payloads/lister og beregninger | Historikk forespør maksimalt 72 punkter per periode. Nyheter starter med 10 synlige meldinger. Sensitivitet har 63 celler som standard, maksimalt 180. Ingen ubegrenset stor hovedliste dokumentert. | Ingen virtualisering eller payloadendring uten representative produksjonsmålinger. |
| Bilder, fonter og asset-cache | Systemfonter; én liten lokal PNG-logo med reserverte dimensjoner. Hashede assets caches immutable; nginx har komprimering. | Ingen dokumentert materiell assetflaskehals. |
| Layout shifts og navigasjonsarbeid | CLS er målt, men ingen stor problematisk shift dokumentert. Navigasjonspreload har 120 ms intensjonsforsinkelse og 30 sekunders cache. | Ingen kosmetisk endring; den lille CLS-avveiningen nedenfor rapporteres. |
| Backend/cache/ferske data | Klientcache revaliderer umiddelbart; eksisterende tester dekker ferske verdier og fallback. Worker-/D1-latens kan fortsatt dominere ekte trafikk. | Lav confidence uten produksjonsmåling; ingen cache-/backendendring. |

## Endring 1: gjenbruk tallformat i NAV-sensitivitet

`frontend/src/NavSensitivityPage.tsx` opprettet språkformat på nytt via
`Number.toLocaleString("nb-NO", options)` for hvert tall på hver render. Matrisen
formaterer både synlig innhold og tilgjengelighetstekst. Selv input som ennå ikke
brukes til en ny beregning utløste 281 slike kall.

Den lokale formatteringsfunksjonen gjenbruker nå én `Intl.NumberFormat` per brukt
presisjon. Bare fire presisjoner brukes: 0, 1, 2 og 4. Formatene opprettes ved
første behov. Null, ikke-endelige tall, minustegn, tusenskille, avrunding og
beregninger er uendret. Ingen komponentmemoisering eller state-refaktorering.

Isolert prøve, før standardvisningen ble endret: instrumentert main-thread-tid
falt fra 775 til 348 ms for 20 tastetrykk; tastetrykk til neste visning fra 49,35
til 32,10 ms. Den endelige kontrollen **uten tellerinstrumentering** gir:

| Mål, 20 tastetrykk / tre serier | Før | Etter begge endringer | Reduksjon |
| --- | ---: | ---: | ---: |
| Main-thread-arbeid, TaskDuration | 614,73 ms | 358,63 ms | 41,7 % |
| JavaScript-arbeid, ScriptDuration | 307,56 ms | 85,70 ms | 72,1 % |
| Median tastetrykk → neste visning | 48,90 ms | 32,40 ms | 33,7 % |

JavaScript-chunken for sensitivitet øker omtrent 50 gzip-bytes i det isolerte
bygget. Cacheobjektet beholder fire små formattere så lenge modulen er lastet.
Ingen formattert verdi caches, så endrede data blir fortsatt formatert på nytt.

## Endring 2: fjern standardvisningens sene modulrequestfase

`frontend/src/InvestorApp.tsx` importerer nå Oversikt direkte. De øvrige elleve
sidene beholder lazy loading. Bootstrap og historikk starter fremdeles bare når
Oversikt velges; en direkte annen rute sender ikke Oversikt-API-kall.

Baseline lastet Oversikt etter inngangspakken og hentet sidekode, CSS og
støttemoduler i en ekstra requestfase. Direkte import fjerner denne fasen og gjør
første nyttige Oversikt-innhold tilgjengelig i det første renderløpet. API-data,
revalidering, fallback og navigasjonssemantikk er uendret.

Den eksisterende kildekontrakttesten krevde lazy Oversikt. Den tidligere
beslutningen i `docs/frontend-critical-path-2026-10-02.md` var basert på sparte
bytes uten Chromium-profil. Testen er oppdatert til dagens dokumenterte valg,
med fortsatt kontroll av lazy NAV og NAV-sensitivitet. Dette er en eksplisitt
avveining, ikke en påstand om at større inngangspakke hjelper alle ruter.

| Oversikt, fem kalde innlastinger | Før | Etter | Endring |
| --- | ---: | ---: | ---: |
| LCP | 720 ms | 464 ms | 35,6 % raskere |
| FCP | 376 ms | 464 ms | 88 ms senere |
| Ressursforespørsler | 13 | 8 | 38,5 % færre |
| API-forespørsler | 3 | 3 | Uendret |
| Overføring, Resource Timing | 111 065 B | 107 323 B | 3,4 % mindre |
| CLS | 0,0381 | 0,0482 | +0,0101 |

FCP gjelder første paint av skallet; den kan bli senere selv om hovedinnholdet
blir klart tidligere. Målt LCP og færre requestfaser er grunnen til valget. CLS
blir litt høyere, og forbedringen fremstilles ikke som en gevinst for alle mål.

| Kontroll ved 1,6 Mbit/s, tre innlastinger | Før | Etter | Endring |
| --- | ---: | ---: | ---: |
| Oversikt LCP | 1 180 ms | 980 ms | 16,9 % raskere |
| Oversikt FCP | 836 ms | 980 ms | 144 ms senere |
| Direkte NAV-sensitivitet LCP | 1 224 ms | 1 272 ms | 3,9 % tregere |
| Direkte NAV-sensitivitet FCP | 812 ms | 852 ms | 40 ms senere |

Den direkte sensitivitet-ruten overfører 102 216 → 110 804 B, altså **8 588 B
mer**, mens antall forespørsler går fra 10 til 9. Uten båndbreddebegrensning er
LCP 772 → 728 ms; dette gir ikke grunnlag for å love samme gevinst på mobilnett.

Vite-buildets inngangs-JavaScript øker fra 229,45 / 72,46 kB gzip til 256,30 /
80,11 kB gzip. Inngangs-CSS øker fra 39,96 / 7,91 til 55,03 / 9,93 kB gzip.
Målefilens separate gzip-størrelser bruker Python gzip nivå 9 og må derfor ikke
blandes med Vites gzip-estimat eller faktisk Resource Timing-overføring.

## Funksjonalitet og kontroll

- `npm run build`: bestått, inkludert TypeScript-kompilering.
- `npm test`: 12 eksisterende frontend-testfiler bestått, blant annet bootstrap,
  revalidering/fallback, navigasjon og finansielle beregninger.
- `PYTHONPATH=backend .venv/bin/python -m pytest -q backend/tests/*frontend*.py
  backend/tests/test_first_load_performance_contract.py
  backend/tests/test_overview_no_blocking_calendar.py`: **49 bestått**.
- 16 068 paritetstilfeller for tallformat: identisk tekst med gammel metode,
  inkludert negative tall, null, NaN, Infinity, negative zero, avrundingsgrenser,
  svært små/store verdier og alle fire presisjoner.
- Browser-snapshots før/etter er identiske for 63 celler i alle fire moduser,
  cellevalg, eksakt scenario med komma-input, ugyldig negativ input, maksimal
  180-cellers matrise, reset til 63 celler, tur/retur Oversikt og 390 px mobil.
  Både synlige tall, aria-labels, toneklasser og scenariodetaljer sammenlignes.
- `git diff --check`: bestått. Frontend har ingen lint-script eller konfigurert
  frontend-linter; en ny lintavhengighet er ikke lagt til.
- Full Worker-paritet og eksisterende brede browser-smoke er ikke kjørt; lokalt
  brukes den avgrensede, representative før/etter-kontrollen beskrevet over.

Endrede kode-/testfiler: `frontend/src/NavSensitivityPage.tsx`,
`frontend/src/InvestorApp.tsx`, `backend/tests/test_first_load_performance_contract.py`.
Ingen commit, push eller deploy er utført.

## Resultat

- **Viktigste flaskehals før:** språkformat ble konstruert hundrevis av ganger per
  tastetrykk; Oversikt krevde en ekstra modulrequestfase etter inngangspakken.
- **Endringer gjort:** fire gjenbrukbare tallformater og direkte import av Oversikt.
- **Måling før:** Oversikt LCP 720 ms; main-thread 614,73 ms per 20 tastetrykk;
  input til neste visning 48,90 ms.
- **Måling etter:** LCP 464 ms; main-thread 358,63 ms; input 32,40 ms.
- **Forbedring:** henholdsvis 35,6 %, 41,7 % og 33,7 % i lokale medianer.
- **Trade-offs:** mer kode/CSS på andre inngangsruter, 8,6 kB ekstra målt på
  sensitivitet, 48 ms senere LCP der ved 1,6 Mbit/s, senere Oversikt-FCP og
  +0,0101 CLS. Ingen svekket datakorrekthet eller feilhåndtering er funnet.
- **Neste mest lovende forbedring:** mål faktisk rutefordeling og bootstrap-/D1-
  latens i produksjon. Undersøk deretter rutespesifikk tidlig moduloppdagelse for
  Oversikt, slik at requestfase-gevinsten kan beholdes uten å belaste andre ruter.

# Cloudflare production target

Denne katalogen er den aktive Cloudflare-native produksjonsimplementasjonen.

## Valgte tjenester

- **Python Workers + FastAPI** – dashboard-API og portert Python-forretningslogikk
- **Workers Static Assets** – React/Vite frontend
- **D1** – strukturert produksjonsdatabase
- **R2** – PDF/råkilder/arkiv og store recovery-payloads i senere fase
- **Cron Triggers** – 30-minutters fast refresh i Phase 15.4
- **Workflows** – tyngre fullrefresh og retries i Phase 15.5
- **Workers Secrets / Secrets Store** – produksjonssecrets

Docker/SQLite beholdes kun som regresjonsreferanse og bootstrap-kilde under cutover.

## Implementert nå

```text
src/
  entry.py
  app.py
  repository.py
  dashboard_service.py
  buyback_service.py
  oslo_calendar.py
  b3_calendar.py
  otec_ingestion.py
  bmob3_ingestion.py
  newsweb_client.py
  newsweb_ingestion.py
  newsweb_buybacks.py
  scheduled.py

migrations/
  0001_initial_schema.sql
  0002_reference_data.sql
  0003_query_indexes.sql
  0004_option_liability.sql
```

Worker-rutene er:

```text
GET /api/health
GET /api/dashboard/summary
GET /api/dashboard/history
GET /api/buybacks/forecast
```

React/Vite ligger på samme Worker-origin. `/api/*` er Worker-first, mens øvrige paths serveres som Static Assets med SPA-fallback.

WorkerEntrypoint har i tillegg en `scheduled(self, controller, env, ctx)`-handler. `wrangler.jsonc` kobler denne til `*/30 * * * *` for den lette innhentingsbanen.

## Phase 15.4.1 – OTEC intradag

Første write-path er CI-validert:

```text
Cron */30 * * * *
  -> Euronext LAST_15_MINUTES
  -> ved behov LAST_HOUR
  -> OTEC ISIN/XOSL/NOK-filter
  -> kilde-dokument i D1
  -> idempotent market_prices LAST/DIRECT
  -> job_runs
```

Semantikken er bevisst lik SQLite-referansen: Euronext-transaksjonen lagres som `LAST`/`DIRECT` og omtales ikke som offisiell sluttkurs.

Intradagspayloaden er eksplisitt størrelsesbegrenset. ZIP-en holdes bounded, mens CSV-medlemmet leses sekvensielt direkte fra ZIP-strømmen i stedet for å ekspanderes til én stor bytes-/tekstbuffer.

## Phase 15.4.2 – BMOB3 intradag og EOD LAST

BMOB3 er koblet til samme 30-minutters Cron og er CI-validert mot referanseimplementasjonen:

```text
Cron */30 * * * *
  -> B3 delayed BMOB3 JSON
  -> 15 min effective market timestamp
  -> market_prices LAST/DIRECT
  -> etter 19:15 São Paulo: idempotent EOD LAST
  -> offisiell COTAHIST CLOSE kan senere oppgradere samme handelsdag
```

B3-responsen er begrenset til 256 KiB. Worker-versjonen bruker ikke hop-by-hop-headeren `Connection`; en egen regresjonstest låser dette fordi Cloudflare ikke tillater denne headeren i Worker-subrequests.

EOD-verdien merkes eksplisitt som en siste forsinket webkurs, **ikke** som offisiell COTAHIST-sluttkurs. Den tyngre daglige COTAHIST-jobben beholdes derfor som sterkere kilde i full refresh.

Scheduler-isolasjonen gjør at en feil i én markedsfeed ikke automatisk stopper den andre: kjøringen registreres som `PARTIAL` når bare én kilde feiler, og `FAILED` først når alle aktive hovedkilder feiler.

## Phase 15.4.3 – OTEC EOD og gap recovery

Worker-banen følger referansens 75-minutters overlap-prinsipp, men unngår en stor dagsfil i normal drift:

```text
30-minutters OTEC refresh
  -> LAST_15_MINUTES
  -> LAST_HOUR
  -> hvis nylig frisk OTEC-poll: ingen dagsfil
  -> ved kaldstart/poll-gap > 75 min: CURRENT_TRADING_DAY
  -> etter 16:45 Oslo: EOD fra dokumentert rolling coverage + siste D1-handel
```

Når den rullerende dekningen er frisk, finaliseres dagens siste kjente OTEC-handel direkte fra D1. EOD-raden er fortsatt `LAST` / `DIRECT` og merkes `FINAL_REPORTED_TRADE_NOT_OFFICIAL_CLOSE`; vi hevder dermed ikke å ha Euronexts offisielle closing-price-felt.

`CURRENT_TRADING_DAY` brukes bare til kaldstart/gap recovery. Den komprimerte recovery-ZIP-en har en hard grense på 32 MiB som kontrolleres mot `Content-Length` **før** `arrayBuffer()` når serveren oppgir lengden. Den utpakkede CSV-en materialiseres aldri som én stor tekstbuffer; bare OTEC-rader beholdes i Python.

Dette er et fail-safe valg mot Workers' 128 MiB minnegrense. Dersom en recovery-ZIP er større enn 32 MiB, feiler OTEC-steget kontrollert og scheduled job blir `PARTIAL` dersom andre kilder fortsatt fungerer. Store recovery-payloads er eksplisitt kandidat for R2 + Workflow i Phase 15.5/15.6, der Cloudflare kan strømme data til R2 uten å holde hele objektet i Worker-minnet.

## Phase 15.4.4 – NewsWeb incremental

NewsWeb er nå en Worker-native inkrementell D1-write-path i samme 30-minutters Cron:

```text
NewsWeb history
  -> 14 dagers overlapp fra siste arkiverte melding
  -> issuer 7759 / OTEC / XOSL-validering
  -> recursive split hvis API-listen melder overflow
  -> korrigerte/superseded meldinger filtreres ut
  -> kilde-dokument + company_news i D1

NewsWeb buybacks
  -> 21 dagers overlapp fra siste daglige/ukentlige buyback-fakta
  -> ukentlig status parseres med samme normalisering som referansen
  -> buyback_programs / buybacks
  -> CONFIRMED fallback-kontantbevegelse
  -> treasury/outstanding share count
```

JSON-responsen er begrenset til 5 MiB, og `Content-Length` kontrolleres før body-lesing når den finnes. Full meldingstekst lagres ikke i D1; vi lagrer SHA-256, metadata og de strukturerte faktaene som trengs for dashboardet.

Parseren er regresjonstestet mot dokumenterte NewsWeb-varianter fra 2023–2025, inkludert legacy første programuke, `Sine the initiation`-feilen, `continuation`-ordlyd og desimalkomma. En egen test skriver ukesfakta mot database bygget fra de faktiske D1-migreringene og verifiserer idempotens.

Kildeprioriteten er bevart fra referanseimplementasjonen: Euronext-fakta rangeres foran NewsWeb når begge finnes. En lik eller svakere kilde får derfor ikke overskrive motstridende sterkere buyback-fakta uten at kjøringen stopper for kontroll.

PDF-vedlegg blir bevisst **ikke** lastet ned og tolket hvert 30. minutt. Ukesmeldingen gir fortsatt bekreftet ukesbeløp, treasury shares og fallback-kontantbevegelse. Daglige PDF-transaksjoner og NewsWeb-PDF-arkiv legges til i full refresh/R2 i Phase 15.5/15.6; de kan da erstatte ukentlig fallback med mer presise daglige kontantbevegelser.

## D1

`0001_initial_schema.sql` er en frosset baseline generert fra SQLite-referansen og skal ikke håndredigeres. Senere datamodellendringer ligger i additive D1-migreringer. `0002_reference_data.sql` oppretter stabile sources/instruments, `0003_query_indexes.sql` inneholder D1-spesifikke read-performance-indekser, og `0004_option_liability.sql` legger til opsjonsfeltene for FULL NAV.

`repository.py` inneholder nå både read-laget og et avgrenset `D1WriteRepository` for scheduled ingestion. Skrivelaget bruker parameterbinding og beholder idempotente unique-key-semantikker for `source_documents` og `market_prices`.

Regenerer/verifiser basis-schema:

```bash
python cloudflare/tools/generate_d1_schema.py
python cloudflare/tools/generate_d1_schema.py --check
```

## Bootstrap og parity

`tools/d1_bootstrap.py` eksporterer en validert SQLite-snapshot til portabel D1-SQL med manifest/hashes. CI importerer denne gjennom faktisk lokal Wrangler D1 og verifierer logical parity og foreign keys.

En populated Worker-fixture importeres også til lokal D1, faktisk `workerd` startes, og HTTP-output for summary/history/forecast må være eksakt lik referansebackenden. Phase 15.4.1–15.4.4 kjøres gjennom den samme Worker-build/runtime-porten, i tillegg til egne OTEC-, BMOB3- og NewsWeb-regresjonstester.

## Ytelseshardening

Buyback-prognosen bruker en bounded OTEC activity-read per forecast i stedet for to D1-spørringer per historisk programuke. Ready-path har en query-budget-regresjonstest slik at D1-querybruk ikke vokser lineært med programmets alder.

D1 har egne indekser for:

```text
buybacks(program_id, trade_date, id)
nav_snapshots(calculation_version, nav_scope, as_of_at)
```

## Security/cache

Statiske assets får browser-hardening via `frontend/public/_headers`, som Vite kopierer til `dist/_headers`. Worker-genererte API-responser får sikkerhetsheadere direkte fra FastAPI-middleware.

Cache-policy:

- health: `no-store`
- summary: 30 sekunder
- history: 15 minutter
- buyback forecast: 15 minutter
- fingerprintede Vite-assets: immutable langtids-cache

## Kontoressurser som gjenstår

Når write-paths og go-live er klare:

```bash
npx wrangler d1 create otello-nav --location=weur
npx wrangler r2 bucket create otello-source-archive
```

Deretter settes faktisk D1-ID i produksjonskonfigurasjonen og den validerte cutover-snapshoten importeres.

## Lokal Worker

Fra repo-root:

```bash
cd frontend
npm ci
npm run build
cd ../cloudflare

python -m pip install workers-py==1.16.4 uv==0.12.3
npm install --no-save wrangler@4.123.0
npx wrangler d1 migrations apply DB --local --config wrangler.worker-test.jsonc
pywrangler deploy --dry-run --config wrangler.worker-test.jsonc
pywrangler dev --config wrangler.worker-test.jsonc
```

## Neste del av Phase 15.4

```text
Dirty-state cash/NAV, inkludert option-aware FULL NAV
```

Dagens synkrone SQLite `fast_refresh.py` skal ikke kopieres direkte inn i Worker-runtime. Nettverkskall, payloadgrenser og D1-writes tilpasses Cloudflare eksplisitt, og tyngre/større payloads flyttes til Workflow/R2 når det er riktigere enn å buffre dem i Worker-minnet.

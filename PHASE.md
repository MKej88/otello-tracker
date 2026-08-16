# Prosjektstatus

## Fase 1 – Fundament

Status: **Ferdig**

- [x] FastAPI-backend
- [x] React/TypeScript-frontend
- [x] Docker Compose + nginx
- [x] GitHub Actions CI
- [x] mørkt dashboard-skjelett

## Fase 2 – Database og datamodell

Status: **Ferdig**

- [x] SQLite med versjonerte/idempotente migreringer
- [x] WAL, foreign keys og busy timeout
- [x] markedsdata, FX, Bemobi-beholdning og OTEC-aksjetall
- [x] cash-ankre og cash-bevegelser
- [x] buybacks og corporate actions
- [x] NAV-snapshots
- [x] meglerestimater/konsensus-tabeller
- [x] kilde-, dokument- og feltbasert provenance/audit trail
- [x] jobbstatus og kildehelse

## Fase 3 – Historiske Otello-ankre

Status: **Ferdig**

- [x] kuraterte Otello-rapportankre fra 2021
- [x] rapportert cash i original valuta
- [x] registrerte/egne/utestående OTEC-aksjer
- [x] Bemobi IPO- og greenshoe-beholdning
- [x] historiske aksjekanselleringer
- [x] NOK 21-distribusjonen i 2022
- [x] kildeprovenance til rapport/melding

## Fase 4 – Historiske markedsdata

Status: **Ferdig og live-validert**

- [x] BMOB3 fra offisiell B3 COTAHIST, 10.02.2021 → 14.08.2026
- [x] BRL/NOK og USD/NOK fra ECB
- [x] OTEC-historikk fra Investing + offisiell Euronext-overlapp
- [x] reversering av OTEC dividend-adjustment før NOK 21-utdelingen
- [x] 498/498 overlappende OTEC-dager avstemt eksakt mot Euronext
- [x] DIRECT/RECONSTRUCTED datakvalitet
- [x] robust B3-nedlasting med retry og manuell ZIP-fallback
- [x] CORE NAV på rapportankre

## Fase 5 – Daglig cash og daglig CORE NAV

Status: **Ferdig og live-validert**

- [x] rapporterte cash-ankre konverteres med historisk ECB FX
- [x] kjente corporate actions legges på faktiske datoer
- [x] residual cash drift avstemmer eksakt mot neste rapporterte anker
- [x] daglig cash-kurve
- [x] daglig Bemobi-markedsverdi
- [x] daglig CORE NAV/aksje
- [x] daglig OTEC-rabatt
- [x] eksplisitt BACKFILLED/DEGRADED/FORECAST_PARTIAL-kvalitet
- [x] historiske residualdiagnoser
- [x] etter fase 6.4: ingen halvårsperioder står igjen som HIGH_RESIDUAL

## Fase 6 – Otello-buybacks og cash-avstemming

Status: **Ferdig for kjent historikk til 14.08.2026**

- [x] deterministisk parser for ukentlige buyback-statusmeldinger
- [x] idempotent oppdatering av buybacks, cash og treasury shares
- [x] historisk buyback-backfill 2022, 2024, 2025 og 2026
- [x] full 2025-buyback-kjede avstemt
- [x] 2026-dekning avstemt gjennom 14.08.2026
- [x] originale utstederavvik beholdes i metadata og korrigeres aldri lydløst
- [x] effektive aksjekapitalankre etter kanselleringer
- [x] H1 2022 AdColony-innbetaling og Bemobi-skatt modellert
- [x] H1 2022 residual redusert fra ca. NOK 1,399 mrd. til ca. NOK 129m
- [x] ingen perioder er lenger flagget HIGH_RESIDUAL

## Fase 7 – Live dashboard

Status: **Ferdig og merget**

- [x] demo-KPI-er fjernet fra API og frontend
- [x] database-backed `/api/dashboard/summary`
- [x] `/api/dashboard/history` med bounded/downsampled historikk
- [x] reelle NAV-, OTEC-, BMOB3-, FX- og cash-KPI-er
- [x] reelle dagsendringer i stedet for hardkodede prosenter
- [x] SVG-graf for NAV vs OTEC uten tung chart-avhengighet
- [x] SVG-graf for historisk NAV-rabatt og gjennomsnitt
- [x] siste buyback og treasury shares i dashboardet
- [x] Bemobi-eksponering fra databasen
- [x] tydelig FORECAST_PARTIAL-varsel for post-anchor cash
- [x] `not_ready` på tom database i stedet for demo/falske tall
- [x] backend- og frontend-CI grønn

## Fase 8 – Samlet refresh-pipeline

Status: **Ferdig og merget**

- [x] én kommando for databaseinit + historikk + markedsdata + buybacks + cash + NAV
- [x] nylig ECB-FX oppdateres automatisk
- [x] gjeldende B3 COTAHIST-år oppdateres automatisk
- [x] buybacks samles før cash/NAV-rebuild
- [x] optional OTEC Euronext/Investing CSV-import i samme jobb
- [x] upstream-feil stopper ikke resten av modellen
- [x] `source_errors` viser nøyaktig hvilken kilde som feilet
- [x] dashboard-staleness beregnes eksplisitt
- [x] `--strict` kan brukes av scheduler/CI
- [x] tester for fail-soft og staleness
- [ ] stabil gratis programmatisk OTEC EOD-kilde; inntil da brukes staleness + CSV-import
- [ ] produksjonsscheduler på Raspberry Pi

## Fase 9 – FULL NAV

Status: **Kode ferdig – CI grønn, klar for merge/live-backfill**

- [x] separat rapporttabell for øvrige nettoeiendeler/-forpliktelser (ONA)
- [x] rapportformel: total assets − cash − Bemobi carrying value − total liabilities
- [x] åtte sikre rapportankre fra 30.06.2022 til 31.12.2025
- [x] 2023/2024 bruker siste restaterte tall fra Annual Report 2025
- [x] hvert anker avstemmes matematisk før lagring
- [x] feltbasert provenance til rapport og rapportlokasjon
- [x] rapport-native USD beholdes og konverteres med historisk USD/NOK
- [x] daglig ONA interpoleres i USD mellom rapportankre
- [x] post-FY25 ONA markeres `FORECAST_PARTIAL`
- [x] separat `FULL` NAV-serie; CORE-serien overskrives aldri
- [x] invariant-test: FULL NAV = CORE NAV + ONA
- [x] dashboard foretrekker FULL når serien finnes og faller ellers tilbake til CORE
- [x] `/api/nav/other-net-assets` og `/api/nav/full`
- [x] refresh-pipelinen bygger CORE → ONA → FULL i riktig rekkefølge
- [x] frontend viser CORE/FULL scope og ONA i modellstatus
- [x] ingen FULL-historikk før 30.06.2022 uten dokumentert ONA
- [ ] kjøre FULL NAV live mot komplett produksjons-/backfilldatabase
- [ ] rekonstruere 2021 transaksjonsbalanser dersom FULL NAV ønskes helt tilbake til Bemobi-IPO

## Neste prioriteringer

1. Kjør Phase 9 FULL NAV live mot den komplette historiske databasen og avstem CORE/FULL-differansen.
2. **21.08.2026:** importer Otello 1H26 og erstatt FORECAST_PARTIAL cash/ONA med nye rapporterte ankere.
3. Finn/valider stabil gratis OTEC EOD-oppdatering eller behold kontrollert CSV-rutine.
4. Bygg Bemobi selskapsmeldinger/dividende/JCP-modul i dashboardet.
5. Bygg Bemobi broker-consensus tracker før Q3.
6. E-postrapporter og varsler.
7. Raspberry Pi + Cloudflare Tunnel/Access deployment.

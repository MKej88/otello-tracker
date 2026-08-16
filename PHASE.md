# Prosjektstatus

## Fase 1 – Fundament

Status: **Ferdig**

- [x] FastAPI-backend
- [x] React/TypeScript-frontend
- [x] Docker Compose
- [x] Health-endepunkt
- [x] GitHub Actions CI
- [x] Mørkt dashboard-skjelett

## Fase 2 – Database og datamodell

Status: **Ferdig**

- [x] SQLite-initialisering ved appstart
- [x] Versjonerte og idempotente migreringer
- [x] WAL, foreign keys og busy timeout
- [x] Referansedata for kilder og instrumenter
- [x] Markedspris- og FX-tabeller
- [x] Bemobi-beholdning og OTEC-aksjetall
- [x] Cash-ankre og cash-bevegelser
- [x] Tilbakekjøpsprogrammer og transaksjoner
- [x] Corporate actions
- [x] NAV-snapshots
- [x] Bemobi/Otello selskapsmeldinger
- [x] Meglerestimater og konsensus-snapshots
- [x] Kilde-/dokumentkobling og provenance/audit trail
- [x] Jobbstatus og kildehelse
- [x] Database-status API
- [x] Automatiske databasetester

## Fase 3 – Historiske Otello-rapportankre

Status: **Ferdig**

- [x] katalogisere primære Otello-rapporter som brukes i historikken
- [x] versjonert, kuratert historikkmanifest med separat korreksjonslag
- [x] rapport-native cash-ankre i USD uten kunstig NOK-konvertering
- [x] eksakte OTEC total-/egne-/utestående aksjer fra 1H21 til FY25
- [x] Bemobi IPO-beholdning: 34 553 860 aksjer / 38,01 % fra første handelsdag
- [x] Bemobi etter greenshoe: 32 719 588 aksjer fra 15.03.2021
- [x] verifisert registreringskjede for OTEC-aksjekanselleringene i 2021–2022
- [x] NOK 21-distribusjonen i 2022
- [x] feltbasert provenance til rapport/melding og side/avsnitt
- [x] idempotent historikkimport ved appstart
- [x] `/api/system/history` med dekning
- [x] automatiske tester for nøkkelankre og avstemminger
- [x] tidligere kjente 2021-gap lukket fra offentlig kildemateriale

## Fase 4 – Historiske markedsdata og første NAV-serie

Status: **Kode og modell ferdig – runtime backfill gjenstår**

- [x] offisiell B3 COTAHIST fixed-width parser for BMOB3
- [x] automatisk B3 årsfil-nedlasting med trygg fallback til manuell ZIP ved CAPTCHA
- [x] ECB EXR CSV-parser og automatisk BRL/NOK + USD/NOK cross-rate
- [x] robust Euronext historical CSV-import for OTEC
- [x] kildefil-hash og source-document-spor for alle backfills
- [x] markedsdatastatus via `/api/system/market-data`
- [x] CLI for B3/ECB/Euronext-backfill
- [x] CORE NAV-motor på rapportdatoer
- [x] historisk CORE NAV-rabatt når OTEC-kurs finnes
- [x] eksplisitt skille mellom `CORE` og senere `FULL` NAV
- [x] komponent-/inputspor og hash per NAV-snapshot
- [x] `/api/nav/core-anchors`
- [x] parser-, database- og NAV-avstemmingstester
- [ ] kjøre full ECB-backfill fra 10.02.2021
- [ ] importere B3 årsfilene 2021–2026
- [ ] importere Euronext OTEC-historikk
- [ ] generere alle tilgjengelige CORE NAV-ankre på produksjons-/lokal database
- [ ] rekonstruere øvrige nettoeiendeler/gjeld og oppgradere fra CORE til FULL NAV

## Neste etter runtime-backfill

- løpende markedsdatajobber
- cash-motor mellom rapportdatoene
- FULL historisk NAV
- daglig NAV-serie og historisk rabattgraf

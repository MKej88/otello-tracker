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

Status: **Ferdig for offentlig tilgjengelig kildemateriale**

- [x] katalogisere primære Otello-rapporter som brukes i historikken
- [x] versjonert, kuratert historikkmanifest
- [x] rapport-native cash-ankre i USD uten kunstig NOK-konvertering
- [x] OTEC total-/egne-/utestående aksjer fra 2022 til 2025
- [x] bekreftet Bemobi-beholdning på 32 719 588 aksjer
- [x] relevante aksjekanselleringer og NOK 21-distribusjonen i 2022
- [x] feltbasert provenance til rapport og side/avsnitt
- [x] idempotent historikkimport ved appstart
- [x] `/api/system/history` med dekning og kjente datagap
- [x] automatiske tester for nøkkelankre og avstemminger
- [ ] eksakt OTEC total-/treasury-/utestående aksjer i 2021 (krever bedre 2021-kilde)
- [ ] eksakt effektiv dato for Bemobi-greenshoe-salget etter IPO

## Neste: Fase 4 – Historiske markedsdata og første NAV-serie

- [ ] BMOB3 daglige sluttkurser fra IPO
- [ ] OTEC daglige sluttkurser
- [ ] historiske BRL/NOK-rater
- [ ] avstemme markedsdata mot rapportdatoer
- [ ] beregne første historiske markeds-NAV
- [ ] beregne historisk NAV-rabatt

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

## Neste: Fase 4 – Historiske markedsdata og første NAV-serie

- [ ] BMOB3 daglige sluttkurser fra IPO
- [ ] OTEC daglige sluttkurser
- [ ] historiske BRL/NOK-rater
- [ ] avstemme markedsdata mot rapportdatoer
- [ ] beregne første historiske markeds-NAV
- [ ] beregne historisk NAV-rabatt

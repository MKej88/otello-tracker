# Otello Tracker – videre plan

## Status 20.08.2026

Cloudflare-produksjonen er live. D1 er autoritativ database, R2 brukes til kildearkiv/snapshots, rask Cron kjører hvert 30. minutt og daglig Full Workflow håndterer tyngre oppdateringer.

Den gamle fase-/go-live-planen er avsluttet. Dette dokumentet viser bare arbeid som fortsatt er relevant.

## Nærmeste finansielle kontrollpunkt

### Otello 1H26 – 21.08.2026

Når rapporten publiseres:

1. importer nytt rapportert cash-anker;
2. avstem ONA/balanse;
3. oppdater rapportert opsjonsforpliktelse og relevante Black-Scholes-input;
4. vurder Bemobi-fordringer/distribusjoner;
5. oppdater dokumenterte driftskostnadsankre;
6. legg inn ny cash-valutafordeling bare dersom rapporten dokumenterer den;
7. bruk rapportert cash-FX i ny valuta-backtest;
8. rebuild CORE/FULL og økonomisk NAV;
9. kjør SQLite/D1-paritet, produksjonspreflight og frontend-smoke.

## Teknisk prioritet

### 1. Flytt finansielle fakta ut av Python-kode

Bemobi-resultater, meglerestimater og konsensus bør gradvis lagres i D1 med kildeprovenance i stedet for å være hardkodet i Python. Tabellenes grunnstruktur finnes allerede.

Målet er at nye rapporter/megleroppdateringer skal være dataoppdateringer, ikke kodeendringer.

### 2. Frontend-smoketester

Legg til et lite sett automatiske tester for aktive visninger:

- Oversikt
- NAV
- Tilbakekjøp
- Bemobi
- Konsensus
- feiltilstand/sist gyldige data

### 3. CI- og supply-chain-herding

- gradvis strengere Ruff-regler;
- vurder Dependabot/Renovate;
- vurder CodeQL;
- lås produksjonskritiske GitHub Actions til immutable commit-SHA-er.

## Prinsipper

- CORE/FULL skal ikke endres skjult av investorjusteringer.
- Økonomisk NAV er et separat investorlag.
- Finansielle fakta skal være kildebelagte.
- Parser og produksjonspreflight skal feile lukket ved tvil.
- D1-migreringer skal være additive, bakoverkompatible og følge `docs/migration-history.md`.

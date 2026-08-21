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

## Teknisk status ferdigstilt 20.08.2026

- Bemobi-resultater, forward-konsensus og historiske konsensussnapshots er flyttet til D1 med kildeprovenance og automatisk innhenting der offentlig kilde finnes.
- Norges Bank er primær kilde for direkte BRL/NOK og USD/NOK, med historisk gjenoppbygging og ECB som bevart fallback/provenance.
- Full Workflow har fornybar writer-lock og tydelig fail-closed klassifisering for kritiske kilde-, NAV- og preflight-feil.
- Aktive API-endepunkter sammenlignes mot SQLite-referansen i CI.
- Aktive investorvisninger har ekte headless browser-smoke i CI: Oversikt, NAV, Tilbakekjøp, Bemobi og Konsensus.
- Produksjonskritiske GitHub Actions er låst til immutable commit-SHA-er, og Dependabot følger GitHub Actions, frontend/npm og backend/pip.

## Teknisk prioritet

### 1. Otello 1H26 – automatisert rapportløp

Neste prioritet er å bruke 1H26 som full produksjonstest av den automatiske rapportkjeden: oppdagelse, PDF-parser, fail-closed validering, rapporterte ankere, NAV-rebuild og preflight. Eventuelle manuelle inngrep skal dokumenteres og reduseres dersom de kan automatiseres uten å svekke kildekontrollen.

### 2. Frontend-feiltilstander

Browser-smoke dekker nå alle aktive normalvisninger. Neste nyttige utvidelse er en deterministisk browser-test av feil ved ny API-henting mens sist gyldige investor-data beholdes, slik at stale-data-varselet ikke kan regressere.

### 3. Videre CI- og supply-chain-herding

- stram Ruff-reglene gradvis uten store støy-PR-er;
- vurder CodeQL som separat sikkerhetskontroll;
- behold immutable Action-SHA-er som obligatorisk CI-regel;
- la Dependabot foreslå oppgraderinger, men krev ordinær CI før merge.

## Prinsipper

- CORE/FULL skal ikke endres skjult av investorjusteringer.
- Økonomisk NAV er et separat investorlag.
- Finansielle fakta skal være kildebelagte.
- Parser og produksjonspreflight skal feile lukket ved tvil.
- D1-migreringer skal være additive, bakoverkompatible og følge `docs/migration-history.md`.

# Driftsrunbook – Otello Tracker

Kort operativ runbook for dagens Cloudflare-produksjon.

## Normal deploy

Normal vei er pull request -> grønn CI -> merge til `main` -> grønn CI på `main` -> automatisk produksjonsdeploy.

Ikke omgå CI for ordinære endringer. Produksjonsdeployen bruker eksakt SHA fra den vellykkede CI-kjøringen.

Etter deploy skal HTTP-akseptansen kontrollere frontend, health, NAV, økonomisk NAV, historikk, tilbakekjøp, Bemobi, konsensus og øvrige aktive investor-API-er.

## Deploy feiler før Worker er publisert

1. Les GitHub Actions-steget som feilet.
2. Skill mellom kode-/buildfeil og Cloudflare-/credential-/nettverksfeil.
3. Ikke gjør manuelle D1-endringer for å «fikse» en vanlig kodefeil.
4. Rett årsaken i ny PR.

## Deploy feiler etter publisering

Produksjonsworkflowen skal forsøke Worker-rollback dersom HTTP-akseptansen feiler etter deploy.

Viktig: Worker-rollback reverserer **ikke** D1-migreringer. Hvis feilen skyldes en migrering, vurder D1 Time Travel og gjenopprett først etter at påvirkningen er forstått.

## Dashboarddata er utdaterte

Kontroller i denne rekkefølgen:

1. `/api/health`
2. `/api/dashboard/summary`
3. `/api/dashboard/report-status`
4. siste fast-refresh-jobb
5. siste Full Workflow
6. source health / komponentdatoer

Finn hvilken kilde som er utdatert før man endrer NAV-modellen. Manglende markedskilde skal behandles som et datainnhentingsproblem, ikke skjules med manuelle finansielle konstanter.

## Fast refresh stopper

Fast refresh kjører hvert 30. minutt.

Kontroller om full Workflow holder writer-lock. Dersom låsen er legitim, skal fast refresh hoppe kontrollert over. Dersom en gammel lås ligger igjen etter et krasj, vil expiry gjøre at den kan overtas senere.

Ikke slett `runtime_state` ukritisk; bekreft først hvilken jobb som eier låsen.

## Full Workflow feiler

Kontroller hvilket trinn som feilet: ECB, B3, CVM, NewsWeb, OTEC, NAV, preflight eller R2.

Full Workflow skal alltid forsøke å frigjøre writer-lock i cleanup. Ved gjentatte feil bør den defekte kilden eller parseren rettes fremfor å omgå preflight.

En produksjonspreflight som sier at data ikke er klare skal tas på alvor. Ikke marker en kjøring som frisk bare for å få grønn status.

## D1-migreringer

Regler:

- migreringer skal være additive og bakoverkompatible;
- bruk aldri et tidligere brukt migreringsnummer på nytt;
- se `docs/migration-history.md` før nye migreringer navngis;
- ta hensyn til at en migrering kan være brukt i en eksisterende database selv om filen senere er fjernet fra Git.

## D1 recovery

D1 Time Travel er primær full-database recovery.

Ved alvorlig datakorrupsjon:

1. stopp eller blokker nye skrivejobber hvis nødvendig;
2. identifiser siste sikre tidspunkt/bookmark;
3. vurder om Worker-versjonen også må rulles tilbake;
4. restore D1 med Time Travel;
5. kjør health/preflight og sentrale API-kontroller;
6. åpne for normale skrivejobber igjen.

Gjør ikke en destruktiv restore bare fordi én ekstern datakilde er midlertidig utilgjengelig.

## R2

R2 brukes til kildearkiv og logiske revisjonssnapshots. Det logiske D1-snapshotet tas søndag og ved månedsslutt.

Ved kontroll av snapshot: verifiser manifest, SHA-256 og at forventede tabeller/chunks er inkludert. R2-snapshot er et tillegg til D1 Time Travel, ikke en erstatning.

## Ny Otello-rapport

Når en ny rapport publiseres:

1. hent og arkiver dokumentet med kildeprovenance;
2. la parseren kjøre fail-closed;
3. kontroller rapportdato, valuta/enhet, balanse og kritiske poster;
4. avstem cash, ONA, aksjetall og opsjonsforpliktelse;
5. vurder Bemobi-fordringer/distribusjoner;
6. rebuild CORE/FULL;
7. oppdater økonomisk NAV-laget bare med dokumenterte nye fakta;
8. kjør SQLite/D1-paritet og produksjonspreflight;
9. kontroller aktive frontend-visninger etter deploy.

Ekstreme avvik mot forrige rapport bør kreve manuell kontroll selv om PDF-parseren teknisk lyktes.

## Secrets og produksjonsinnstillinger

Ekte tokens og nøkler skal ligge i GitHub/Cloudflare secrets/variables. `.env.example` er kun for lokal Docker/SQLite-referanse.

Ikke legg produksjonscredentials, rå tokens eller private kildefiler i Git.

# Arkitektur – Otello Tracker

Dette dokumentet beskriver dagens produksjonsarkitektur. Historiske migrerings- og go-live-planer er fjernet fra aktiv dokumentasjon.

## Produksjonsplattform

Produksjon kjører på Cloudflare Workers Paid:

```text
Nettleser
   |
   v
Cloudflare Worker + Workers Static Assets
   |
   |-- React/Vite frontend
   |-- Python Worker API (/api/*)
   |
   +--> D1   autoritativ strukturert produksjonsdatabase
   +--> R2   råkilder, PDF-er og logiske revisjonssnapshots
   +--> Cron */30 * * * *
   +--> Workflow 35 3 * * * UTC
```

SQLite/Docker-implementasjonen i `backend/` er en deterministisk referanse- og regresjonsmotor. Den er ikke produksjonsdatabasen.

## Frontend

Aktive hovedvisninger:

- Oversikt
- NAV
- Tilbakekjøp
- Bemobi
- Konsensus

Historikk, Nyheter og Innstillinger ligger fortsatt i navigasjonen som inaktive områder og skal ikke beskrives som ferdige sider.

Frontend leveres som Workers Static Assets på samme domene som API-et. `/api/*` går gjennom Worker-koden.

## API

De sentrale investorendepunktene omfatter:

```text
GET /api/health
GET /api/market/quotes
GET /api/dashboard/summary
GET /api/dashboard/economic
GET /api/dashboard/waterfall
GET /api/dashboard/fx-backtest
GET /api/dashboard/history
GET /api/dashboard/report-status
GET /api/buybacks/forecast
GET /api/buybacks/dashboard
GET /api/bemobi/dashboard
GET /api/bemobi/consensus
GET /api/bemobi/source-status
```

Referansebackend og Cloudflare Worker skal beholde samme finansielle semantikk. Produksjons- og Worker-smoketester dekker de aktive frontend-visningene.

## Finansielle lag

Tre lag holdes eksplisitt adskilt:

1. **CORE NAV** – Bemobi-markedsverdi + kontantbeholdning.
2. **FULL NAV** – CORE NAV + øvrige nettoeiendeler/-forpliktelser.
3. **Økonomisk NAV** – investorjustert lag som blant annet kan ta hensyn til dokumentert valutaendring, økonomisk opsjonsoverheng og estimerte driftskostnader.

Økonomisk NAV erstatter ikke de regnskapsmessige CORE/FULL-seriene.

Se `docs/economic-nav.md` og `docs/option-liability.md` for modellbeskrivelse.

## Datakilder

### Otello

- selskapets rapporter og investorinformasjon
- NewsWeb for regulatoriske meldinger og tilbakekjøp
- Euronext delayed-data for OTEC-markedsdata og recovery

### Bemobi

- B3 COTAHIST for offisiell BMOB3-sluttkurs
- CVM for regulatoriske metadata og dokumentstatus
- Bemobi IR for eierandel og analytikerdekning
- offentlige MarketScreener-/XP-data når de kan verifiseres og spores

### Valuta

- Norges Banks åpne EXR-API er primærkilde for direkte BRL/NOK og USD/NOK, både løpende og historisk.
- D1 vedlikeholder en rullerende tiårsserie med daglige Norges Bank-kurser. Første Full Workflow etter manglende dekning backfiller serien automatisk.
- Når flere kilder finnes for samme kursdato, velges Norges Bank foran ECB. En nyere fallback-dato velges fortsatt foran en eldre Norges Bank-dato; ferskhet går altså foran kildeprioritet.
- Etter en tiårsbackfill revalueres opprinnelige USD/BRL-baserte kontantankre og kontantstrømmer, og eksisterende historiske CORE/FULL NAV-datoer bygges på nytt deterministisk.
- Daglige referansekurser og backfill-responser arkiveres i R2 og lagres med `NORGES_BANK`-proveniens i D1.
- Historiske ECB-krysskurser beholdes som eldre provenance, kontrollgrunnlag og fallback, men oppdateres ikke lenger i produksjon og er ikke primær historisk serie.

Kildedata skal ha provenance der de påvirker finansielle beregninger. CVM-metadata alene skal ikke skape finansielle fakta.

## Oppdateringsbaner

### Rask oppdatering

Cloudflare Cron kjører hvert 30. minutt. Banen er bounded og håndterer lette, inkrementelle oppdateringer som markedsdata, NewsWeb og berørte NAV-lag.

### Full oppdatering

Cloudflare Workflow kjører daglig kl. 03:35 UTC og håndterer tyngre datakilder, inkludert Norges Bank-valuta, avstemming, NAV-oppdatering, produksjonspreflight og R2-snapshot ved behov.

Hvis den rullerende tiårsdekningen fra Norges Bank mangler, utvider Full Workflow valutahentingen til hele perioden og rebuild-er deretter eksisterende historiske NAV-datoer med de direkte NOK-kursene. Rebuild-en oppretter ikke kunstige NAV-datoer; den oppdaterer kun historikk som allerede har nødvendige pris- og modellankre.

Rask og full bane bruker samme D1-baserte writer-lock. Låsen skal alltid frigjøres også ved feil, og har i tillegg expiry som siste sikkerhetsnett.

## Deploy

Endringer går via pull request og obligatorisk CI. Produksjonsdeploy starter først etter grønn CI på `main` og bruker eksakt testet commit-SHA.

Deploykjeden:

```text
PR -> CI -> merge main -> CI main -> production gate -> deploy -> HTTP-akseptanse
```

Produksjonsakseptansen tester både grunnleggende NAV-endepunkter og API-ene som aktive frontend-visninger er avhengige av. Worker rulles tilbake dersom etterkontrollen feiler.

D1-migreringer rulles ikke tilbake sammen med Worker. De skal derfor være additive og bakoverkompatible.

## Recovery

- **D1 Time Travel** er primær korttidsmekanisme for databasegjenoppretting.
- **R2 logical snapshot** er et ekstra revisjons-/gjenopprettingslag og tas søndag og ved månedsslutt.
- `cloudflare/tools/d1_bootstrap.py` beholdes som deterministisk eksport-/verifiseringsverktøy for referanse og recovery, men den gamle engangs-workflowen for produksjonsbootstrap er fjernet.

Se `docs/runbook.md` for operative tiltak.

## Migreringer

Migreringsnumre som har vært brukt i produksjonsnære grener skal aldri gjenbrukes selv om funksjonen senere fjernes fra kildekoden. Se `docs/migration-history.md`.

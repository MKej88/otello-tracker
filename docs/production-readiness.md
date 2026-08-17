# Production readiness – Cloudflare

Dette dokumentet beskriver produksjonsporten for Cloudflare-versjonen av Otello-trackeren.

Dagens Docker/SQLite-implementasjon er **referanseimplementasjonen** under migreringen. Cloudflare-go-live skal ikke skje før Worker/D1-versjonen gir samme finansielle resultater.

## 1. D1 schema parity

Før produksjon:

- alle nødvendige tabeller skal finnes som D1-migrations;
- constraints/indekser som påvirker dataintegritet skal være portert;
- finansielle felt og provenance-relasjoner skal ha samme semantikk som referansedatabasen;
- schema parity-test skal passere.

## 2. Historisk bootstrap

Den validerte referansehistorikken skal importeres til D1:

- OTEC/BMOB3 priser;
- BRL/NOK og USD/NOK;
- cash anchors/movements;
- Bemobi holdings;
- corporate actions;
- buyback-programmer/transaksjoner;
- CORE/FULL NAV-historikk;
- NewsWeb/CVM metadata;
- runtime/job status der det er relevant.

Importen skal verifiseres med row counts og sentrale kontrollverdier, ikke bare «import completed».

## 3. API parity

Cloudflare Worker skal levere samme kontrakter som dashboardet bruker i dag.

Minstekrav:

- `/api/health`;
- dashboard summary;
- NAV history;
- buyback forecast;
- freshness/component dates;
- Bemobi/news-data som frontend faktisk bruker.

For et fast sett kontroll-datoer skal output sammenlignes med referansebackend.

## 4. Live data

Følgende skal være bekreftet på Cloudflare:

- OTEC delayed intradag + EOD;
- BMOB3 delayed intradag + EOD/CLOSE;
- ECB FX;
- NewsWeb incremental;
- buyback cash/program terms;
- dagens cash/CORE/FULL snapshot.

`ALIGNED`, `MIXED`, `STALE` og `UNKNOWN` skal fortsatt beskrive faktisk inputferskhet.

## 5. Scheduling

Fastløpet skal kjøres med Cloudflare Cron Trigger hvert 30. minutt.

Tyngre fullrefresh skal kjøres som Workflow/scheduled pipeline med retries per kilde/trinn.

Cron-tid er UTC. Markedsdager/-tider skal derfor bestemmes av eksisterende Oslo/B3-kalenderlogikk og eksplisitte timezone-konverteringer.

## 6. D1 og recovery

D1 er autoritativ produksjonsdatabase.

Før go-live:

- D1 Time Travel/restore skal testes;
- migrations skal kunne kjøres deterministisk;
- backup/export-rutine skal dokumenteres;
- ingen kode skal anta en persistent lokal SQLite-fil i Worker-runtime.

## 7. R2

R2 skal brukes til kildeobjekter som ikke hører hjemme i D1:

- NewsWeb-PDF-er;
- rå CSV/ZIP-filer som beholdes;
- historiske importfiler;
- eventuelle eksport/snapshots.

R2 skal ikke brukes som direkte SQLite-filsystem.

## 8. Security

Før produksjon:

- secrets skal ligge i Workers Secrets/Secrets Store;
- ingen API-token skal være i Git;
- API-et skal være same-origin med frontend eller ha eksplisitt CORS-policy;
- kun nødvendige offentlige endpoints skal eksponeres;
- rate/abuse-beskyttelse skal vurderes på Worker/Cloudflare-nivå;
- dependency/audit CI skal være grønn.

## 9. Workers-plan og limits

Free-planen skal ikke antas å være tilstrekkelig uten måling. Produksjonsjobbene må måles mot Worker CPU, memory og subrequest limits.

Utgangspunktet er Workers Paid for produksjon. Dersom måling senere dokumenterer at Free-grensene holder med god margin kan dette revurderes.

## 10. Deploy

Go-live krever:

1. grønn backend/frontend-regresjons-CI;
2. grønn Cloudflare Worker build/dry-run;
3. D1 migrations;
4. historisk bootstrap/parity;
5. Cron/Workflow test;
6. R2 test;
7. deploy fra `main`;
8. custom domain/HTTPS;
9. observability/logging;
10. full end-to-end data-health/preflight.

## 11. Otello 1H26

Etter rapporten 21.08.2026:

1. importer rapporterte cash-/balanseankre i referansemodellen;
2. avstem ONA;
3. rebuild CORE/FULL;
4. kontroller residualer/aksjetall;
5. importer samme verifiserte fakta til D1;
6. bruk nye tall som parity-kontroll før Cloudflare-go-live.

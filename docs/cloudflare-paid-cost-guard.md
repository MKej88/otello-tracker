# Cloudflare Workers Paid – ytelse og kostnadssikring

Dette dokumentet er produksjonspolicy for Otello NAV på Workers Paid. Målet er høy responshastighet og nok compute til datainnhenting, uten å åpne for unødvendig eller ukontrollert forbruk.

## Prinsipper

1. **Statiske filer skal ikke gå gjennom Worker-kode.** Frontend bygges som Workers Static Assets. Bare `/api/*` bruker Worker-kode.
2. **Betalt compute brukes til tunge bakgrunnsjobber, ikke som standardbudsjett for alle forespørsler.** Produksjonsgrensen er 60 000 ms CPU og 500 subrequests per invocation, selv om Workers Paid tillater høyere maksimum.
3. **API-responser caches på Workers-edge.** Dashboard-sammendrag og Economic NAV har kort TTL, mens historikk, tilbakekjøpsprognose og valuta-backtest caches lenger.
4. **Observability samples.** Produksjonslogger lagres for 5 % av invocations. Tracing er avslått som standard.
5. **D1-spørringer skal være indekserte og avgrensede.** Query-parametre er allerede bounded i API-et; egne kostnads-/ytelsesindekser ligger i migrasjonene.
6. **R2-logisk snapshot er ikke daglig backup på Paid-planen.** D1 Time Travel er primær korttids-gjenoppretting. R2-snapshot tas ukentlig og ved månedsslutt for revisjons-/langtidsformål.
7. **Store Workflow-resultater skal ikke brukes som datalager.** D1/R2 er autoritative. Workflow state skal bare inneholde kompakte kontrollresultater.

## Viktig om kostnadstak

Workers Paid har inkludert månedsforbruk, men overforbruk faktureres. Cloudflare Budget Alerts er varsling, ikke et hardt stopp. Derfor kan applikasjonskode alene ikke garantere en øvre faktura dersom en offentlig Worker angripes med svært mange distribuerte forespørsler.

Den sterkeste kostnadsbeskyttelsen er å blokkere misbruk **før Worker-koden starter**.

## Obligatorisk før offentlig produksjon

### 1. Bruk eget domene

Sett `CLOUDFLARE_CUSTOM_DOMAIN` i GitHub production environment. Da settes `workers_dev=false`, og API-et kan beskyttes med WAF på sonen.

### 2. Lag WAF rate limiting-regel for API-et

Anbefalt utgangspunkt for dette private investorverktøyet:

- filter: URI path starter med `/api/`
- teller: per klient-IP
- terskel: **120 forespørsler per minutt per IP**
- handling: **Block**
- varighet: **10 minutter**

Normal dashboardbruk ligger svært langt under dette. Reglens formål er å stoppe en enkel bot, feilsløyfe eller aggressiv klient før forespørslene når Worker-koden.

Hvis siden senere blir offentlig/populær, skal terskelen vurderes mot reell trafikk før den endres.

### 3. Opprett lave Budget Alerts

I Cloudflare Dashboard:

`Manage Account → Billing → Billable Usage → Create budget alert`

Anbefalt:

- første varsel: **USD 1** i usage-based spend
- andre varsel: **USD 5**

Workers Paid-abonnementets faste månedspris inngår ikke i disse tersklene. Varslene er bare informasjonsvarsler og kan komme etter at forbruket allerede har skjedd.

### 4. Slå på D1 billing notifications

Aktiver varsler for:

- Rows Read
- Rows Written

Dette gir en ekstra alarm dersom en query-regresjon begynner å lese eller skrive unormalt mye.

## Produksjonsgrenser i repoet

`cloudflare/tools/render_production_config.py` setter:

```text
CPU per invocation:          60 000 ms
Subrequests per invocation:  500
Workers Caching:             på
Workers Logs sampling:       5 %
Tracing:                     av
```

Disse grensene er bevisst betydelig lavere enn Workers Paid-plattformens maksimum.

## Cache-policy

| Endepunkt | Nettleser | Cloudflare-edge |
|---|---:|---:|
| `/api/dashboard/summary` | 15 s | 60 s |
| `/api/dashboard/economic` | 15 s | 60 s |
| `/api/buybacks/forecast` | 5 min | 15 min |
| `/api/dashboard/history` | 5 min | 30 min |
| `/api/dashboard/fx-backtest` | 30 min | 6 t |
| `/api/health` | ingen | ingen |

Cache reduserer CPU og D1-belastning, men cached Worker-requests teller fortsatt som Workers requests. WAF er derfor nødvendig dersom målet er sterk beskyttelse mot request-overforbruk.

## R2 og D1

D1 Time Travel på Paid-planen brukes for korttids-gjenoppretting. R2-logiske snapshots tas:

- hver søndag;
- ved hver månedsslutt.

Rå kildefiler som er nødvendige for provenance/audit arkiveres fortsatt etter den eksisterende content-addressed R2-policyen.

## Drift

Ved uventet bruk:

1. se `Workers & Pages → Billable Usage`;
2. se CPU time og requests per Worker;
3. kontroller D1 Rows Read / Rows Written;
4. kontroller R2 Class A / Class B og storage;
5. stram WAF-regelen før du øker Worker-grensene;
6. øk aldri `cpu_ms` eller `subrequests` bare for å skjule en ytelsesfeil.

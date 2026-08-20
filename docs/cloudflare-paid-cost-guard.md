# Cloudflare Workers Paid – ytelse og kostnadssikring

Dette er produksjonspolicyen for Otello Tracker på Workers Paid. Målet er nok compute til datainnhenting og analyse uten unødvendig eller ukontrollert forbruk.

## Prinsipper

1. **Statiske filer går ikke gjennom Worker-kode.** Workers Static Assets håndterer frontend; `/api/*` går gjennom Worker.
2. **Compute er begrenset bevisst.** Produksjonsgrensen er 60 000 ms CPU og 500 subrequests per invocation.
3. **API-cache brukes målrettet.** Statiske assets arver ikke global Worker-cache.
4. **Observability er samplet.** Invocation logs lagres med 5 % sampling; tracing er av som standard.
5. **D1-spørringer skal være indekserte og bounded.** Query-parametre og produksjonsindekser skal begrense unødvendige rows read/written.
6. **D1 Time Travel er primær korttids-recovery.** R2-logisk snapshot tas søndag og ved månedsslutt for revisjons-/ekstra recoveryformål.
7. **Workflow state er ikke datalager.** D1/R2 er autoritative lagre.

## Kostnadsvern

Workers Paid har inkludert forbruk, men overforbruk kan faktureres. Budget Alerts er varsling, ikke et hardt kostnadstak. Den viktigste beskyttelsen mot unødvendige requests er derfor å stoppe misbruk før Worker-koden starter.

### Custom domain og WAF

Produksjon bruker custom domain med `workers_dev=false`. `/api/*` skal beskyttes av WAF/rate limiting på sonen.

Et forsiktig utgangspunkt er:

- Cloudflare Free-sone: 20 forespørsler per 10 sekunder per klient-IP;
- Pro eller høyere: 120 forespørsler per minutt per klient-IP, med lengre blokkering dersom planen støtter det.

Tersklene skal vurderes mot faktisk trafikk. WAF rate limiting er ikke et matematisk globalt kostnadstak, men reduserer risikoen for enkle bots, feilsløyfer og aggressive klienter.

### Budget Alerts

Lave varsler er satt som operativt kostnadsvern. Et fornuftig nivå for dette private investorverktøyet er varsling ved svært lav usage-based spend, for eksempel USD 1 og USD 5.

Budget Alerts behandles etterskuddsvis og skal derfor kombineres med WAF og tekniske grenser.

### D1-overvåkning

Følg D1 Rows Read og Rows Written i Cloudflare usage/analytics. Separate D1-spesifikke usage-billing-varsler er ikke en forutsetning i dagens oppsett; kostnadskontrollen baseres på faktisk Billable Usage, D1-metrikker, Budget Alerts og WAF.

## Produksjonsgrenser

`cloudflare/tools/render_production_config.py` setter:

```text
CPU per invocation:                60 000 ms
Subrequests per invocation:        500
Workers Caching, API-entrypoint:   på
Global Workers Caching:            av
Workers Logs sampling:             5 %
Tracing:                           av
```

Øk ikke `cpu_ms` eller `subrequests` bare for å skjule en ytelsesregresjon.

## Cache

Korte investorendepunkter som summary/economic har kort cache. Historikk, forecast og FX-backtest kan caches lenger fordi de endres sjeldnere.

Statiske React/Vite-filer ligger utenfor `/api/*` og leveres direkte gjennom Workers Static Assets.

## R2 og D1

D1 Time Travel brukes ved full database-recovery. R2 logical snapshots tas:

- hver søndag;
- ved månedsslutt.

Rå kildefiler med provenance-/revisjonsverdi arkiveres etter content-addressed policy.

## Ved uventet bruk

1. kontroller Workers Billable Usage;
2. kontroller requests og CPU time;
3. kontroller D1 Rows Read / Rows Written;
4. kontroller R2 Class A / Class B og storage;
5. identifiser hvilke endpoints eller bakgrunnsjobber som driver forbruket;
6. stram WAF eller rett query-/kodefeilen før ressursgrenser økes.

Se også `docs/runbook.md`.

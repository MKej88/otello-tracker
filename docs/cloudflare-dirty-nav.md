# Cloudflare dirty cash og NAV

Sist oppdatert: 17.08.2026.

Denne delen fullfører den lette 30-minutters Cloudflare-banen. Målet er ikke å kopiere hele SQLite-fullrefreshen inn i en Worker, men å beregne dagens dashboardverdier på nytt når de D1-faktaene som faktisk inngår har endret seg.

## Kjørerekkefølge

```text
OTEC / BMOB3 / NewsWeb
  -> dirty cash
  -> CORE NAV
  -> ONA dersom kalenderdato mangler
  -> FULL NAV
```

Rekkefølgen følger referansejobben: kontantgrunnlaget må være oppdatert før CORE, og FULL kan først beregnes når både CORE og dagens ONA finnes.

## Dirty cash

`cash_refresh.py` lager en stabil SHA-256-signatur av kontantankere, kontantbevegelser, relevante corporate actions, Bemobi-holdinger og USD/BRL-FX-grunnlaget. Signaturen lagres i `runtime_state`.

Hvis signaturen er uendret og kontantkurven allerede dekker måldatoen, hoppes hele rebuilden over. Det er viktig på en 30-minutters Cron fordi historiske dagsrader ellers ville blitt skrevet på nytt uten ny informasjon.

Når rebuild er nødvendig:

- rapporterte cash-ankere konverteres til NOK med nærmeste FX innen syv dager;
- kjente kontantbevegelser legges eksplisitt inn;
- mellom to rapporterte ankere fordeles restleddet lineært over kalenderdagene;
- en ukentlig buyback-bevegelse som krysser et rapportert cash-anker ekskluderes fra den eksplisitte post-anchor-delen for å unngå dobbelttelling;
- etter siste rapporterte anker brukes kun kjente flows, med kvalitet `FORECAST_PARTIAL`;
- utdaterte dagsrader ryddes med to datogrenser, ikke et dynamisk `NOT IN` med én D1-parameter per historisk dag.

Metodikken beholder referansens `linear-residual-between-reported-anchors-v2-cross-anchor-safe` og `known-flows-only-forecast-v2-cross-anchor-safe`.

## CORE NAV

CORE bruker uendret beregningsversjon:

```text
core-market-nav-daily-v1
```

Formel:

```text
Bemobi-verdi = Bemobi-aksjer × BMOB3-kurs × BRL/NOK
CORE NAV     = Bemobi-verdi + cash
CORE/aksje   = CORE NAV / utestående Otello-aksjer
```

OTEC, BMOB3 og BRL/NOK kan bruke siste tilgjengelige verdi innen syv kalenderdager. Hvis en markedsverdi er eldre enn måldatoen, eller cash er `FORECAST_PARTIAL`, merkes snapshotet `ESTIMATED`.

## Other net assets og opsjonsforpliktelse

ONA beregnes som:

```text
base ONA ex option
+ aktiv Bemobi-fordring
- kontantoppgjort Otello-opsjonsforpliktelse
```

Bemobi-dividende/JCP er aktiv fordring fra ex-dato til betalingsdato. Når en rapportert ONA-anker inneholder en eksplisitt tilknyttet fordring, brukes dette som kalibreringsanker; ellers beholdes bruttoestimatet.

Opsjonsforpliktelsen følger Phase 15.3.2:

- 4,1 millioner opsjoner;
- tildelingsdato 15.09.2025;
- opprinnelig strike NOK 12,5637;
- strike reduseres for senere betalte Otello-utdelinger;
- Black-Scholes mark-to-market mot OTEC;
- risikofri rente og volatilitet interpoleres frem til rapportankeret 31.12.2025;
- rapportert USD 314k per 31.12.2025 brukes til å kalibrere recognition factor;
- etter siste rapporterte anker holdes recognition factor konstant inntil ny rapport eller annet kvalifiserende evidensgrunnlag.

Fast refresh bygger ONA bare når måldatoen mangler. Det speiler referansejobben og hindrer at intradagssvingninger i OTEC omskriver samme dags ONA flere ganger. Ny rapport/full refresh kan fortsatt erstatte eller bygge historikken på nytt.

## FULL NAV

FULL bruker uendret beregningsversjon:

```text
full-market-nav-daily-v2
```

Formel:

```text
FULL NAV   = CORE NAV + ONA
FULL/aksje = FULL NAV / utestående Otello-aksjer
```

Opsjonsforpliktelsen ligger eksplisitt i ONA-komponentene og provenance-dataene til FULL-snapshotet.

## NAV-dato

På en faktisk live kalenderdag kan dagens dato brukes når D1 har minst én OTEC/BMOB3-markedsrad for datoen. Ellers brukes seneste OTEC-handelsdato på eller før måldatoen. Dette beholder helge-/helligdagsatferden fra referanseimplementasjonen.

## Testkrav

Phase 15.4.5 skal ikke merges før følgende er grønt:

1. Worker cash = SQLite-referanse på samme databasegrunnlag;
2. andre cash-kjøring hopper over rebuild når input-signaturen er uendret;
3. Worker opsjonsforpliktelse = SQLite-referanse;
4. Worker CORE NAV = SQLite-referanse;
5. FULL NAV avstemmer eksakt til `CORE + ONA`;
6. D1-migrasjonsschemaet aksepterer alle writes;
7. Python Worker dry-run og faktisk `workerd` består eksisterende CI-port.

Tyngre NewsWeb-PDF-er, daglige buyback-transaksjoner, CVM/B3-reconciliation og andre fullrefresh-kilder forblir i Phase 15.5/15.6.

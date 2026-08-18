# Økonomisk NAV-overlay

## Formål

`CORE NAV` og `FULL NAV` beholdes som validerte regnskaps-/avstemmingsserier. Et separat **økonomisk NAV** viser en investorjustert verdi mellom rapportdatoer uten å skrive om CORE/FULL.

## Formel

```text
Økonomisk NAV
= FULL NAV
+ dokumentert valutaendring på cash
- (økonomisk opsjonsverdi - regnskapsført/modellert opsjonsforpliktelse)
- estimerte driftskostnader siden siste rapporterte cash-anker
```

Det ekstra opsjonsoverhenget kan aldri bli negativt.

## Kildebelagte driftskostnader

Driftskostnadsforutsetningene ligger i `backend/app/history/data/economic_nav_inputs.json` og seeder ordinære `source_documents`. De er dermed med i curated fingerprint, D1-bootstrap, provenance og logisk avstemming.

For cash-ankeret 31.12.2025 brukes:

### Base

- kildeperiode: 2H25
- employee benefits ekskl. aksjebasert kompensasjon: ca. USD 0,596m
- other operating expenses: ca. USD 0,425m
- sum: **USD 1,021m over 184 kalenderdager**
- annualisert run-rate: ca. USD 2,03m

### Konservativ sensitivitet

- kilde: revidert Annual Report 2025
- operating expenses ekskl. aksjebasert kompensasjon: **USD 2,641m for FY25**

Den daglige run-raten akkumuleres fra siste rapporterte cash-anker og konverteres med fersk USD/NOK innenfor modellens syvdagers FX-lookback.

Renteinntekter estimeres ikke. Dette holder overlayet konservativt og unngår en ekstra antakelse om fremtidig kontantnivå/rente.

## Cash-valuta

Årsrapporten viser at Otello har bankinnskudd i flere valutaer og at valutaendringer faktisk påvirker cash. Økonomisk NAV revaluerer derfor dokumentert valutaeksponering mellom rapportdatoer.

For 31.12.2025 er følgende lagret som kildebelagt cash-FX-anker, uttrykt i USD-ekvivalent ved rapportdato:

- USD-bankkonti: **USD 1,217m**
- BRL-bankkonti: **USD 12,169m**
- total rapportert cash: **USD 15,881m**
- rest som ikke er eksplisitt valutafordelt i kilden: **USD 2,495m**

Den siste delen lagres som `UNALLOCATED`.

### Prinsipp

```text
USD-komponent → revalueres med USD/NOK
BRL-komponent → rekonstrueres til BRL på ankerdato og revalueres med BRL/NOK
UNALLOCATED   → holdes på ankerverdi i NOK
```

Dermed får vi løpende valutaeffekt der det finnes dokumentasjon, men gjetter ikke at residualen ligger i NOK, USD, BRL eller en annen valuta.

Hvis en ny rapportert cash-anchor ikke har en matching dokumentert valutafordeling, brukes ingen cash-FX-justering for det nye ankeret. Kvaliteten vises eksplisitt i API-et.

## Opsjon

Eksisterende FULL NAV bruker recognition-/calibration-faktoren for den regnskapsmessig modellerte kontantoppgjorte opsjonsforpliktelsen. Økonomisk NAV viser i tillegg hele modellerte Black-Scholes-bruttoverdien og trekker differansen:

```text
Ekstra opsjonsoverheng
= max(0, full Black-Scholes-bruttoverdi - recognition-basert forpliktelse)
```

Dette endrer ikke recognition-faktoren i FULL NAV.

## Automatisk reset ved ny rapport

Driftskostnadsakkumuleringen starter alltid på nyeste `REPORTED` cash-anker. Når en nyere rapport legges inn:

1. gammel akkumulering stopper;
2. cost accrual settes til null på ny ankerdato;
3. ny akkumulering starter fra det nye rapporterte cash-nivået;
4. driftskostnadsankeret skal oppdateres når rapporten gir et bedre observerbart run-rate-grunnlag;
5. cash-FX revalueres bare dersom det finnes en matching dokumentert valutafordeling.

## API

```text
GET /api/dashboard/economic
```

Returnerer blant annet:

- regnskapsmessig FULL NAV per aksje;
- økonomisk NAV per aksje;
- konservativ økonomisk NAV;
- rabatt til økonomisk NAV;
- økonomisk cash;
- `cash_fx` med justering, dekningsgrad og kildekvalitet;
- regnskapsført og økonomisk opsjonsverdi;
- ekstra opsjonsoverheng;
- driftskostnad siden cash-anker;
- source document IDs/metodikk for kostnadsankrene.

Hvis FULL og CORE ikke er på samme dato, nødvendige markeds-/FX-input mangler eller driftskostnadsankrene mangler, returneres `ready=false` i stedet for et delvis skjult estimat.

## Kilde

Primær kilde for 2025-ankrene er **Otello Corporation ASA – Annual Report 2025**. Kilde-URL og locator lagres sammen med de kuraterte inputene i source-document provenance.

# Økonomisk NAV-overlay

## Formål

`CORE NAV` og `FULL NAV` beholdes som validerte regnskaps-/avstemmingsserier. Et separat **økonomisk NAV** viser en investorjustert verdi mellom rapportdatoer uten å skrive om CORE/FULL.

## Formel

```text
Økonomisk NAV
= FULL NAV
+ kildebasert valutaendring på cash
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

Den daglige run-raten akkumuleres fra siste rapporterte cash-anker og konverteres med fersk USD/NOK innenfor modellens syvdagers FX-lookback. Renteinntekter estimeres ikke.

## Cash-valuta

### 31.12.2025: full kildebasert allokering

Årsrapporten opplyser at konsernets kontantinnskudd holdes i **NOK, USD og BRL**. Valutaeksponeringstabellen oppgir samtidig USD- og BRL-bankkontiene, mens total cash rapporteres separat.

Det lagrede cash-FX-ankeret er derfor:

- USD-bankkonti: **USD 1,217m**
- BRL-bankkonti: **USD 12,169m** i USD-ekvivalent
- NOK: **USD 2,495m** i USD-ekvivalent på ankerdato
- total rapportert cash: **USD 15,881m**

NOK-beløpet er ikke en direkte rapportert NOK-linje. Det er en **avstemt residual**:

```text
USD 15,881m total cash
- USD 1,217m USD-bankkonti
- USD 12,169m BRL-bankkonti i USD-ekvivalent
= USD 2,495m NOK-residual i USD-ekvivalent
```

Klassifiseringen er kildebasert fordi rapporten begrenser de oppgitte kontantvalutaene til NOK, USD og BRL. Komponenten lagres derfor som `NOK` med kvalitet `RECONCILED_RESIDUAL_NOK`, ikke som `UNALLOCATED`.

### Prinsipp i NAV-beregningen

```text
USD-komponent → revalueres med USD/NOK
BRL-komponent → rekonstrueres til BRL på ankerdato og revalueres med BRL/NOK
NOK-komponent → holdes fast i NOK
UNALLOCATED   → holdes på ankerverdi i NOK som bakoverkompatibel fail-safe
```

For 31.12.2025-ankeret gir dette **100 % kildebasert dekningsgrad** og kvalitet `FULL_EXPOSURE_REVALUATION`.

Dette endrer først og fremst provenance og modellkvalitet. Den tidligere `UNALLOCATED`-delen ble allerede holdt fast på ankerverdi i NOK, så omklassifiseringen til kildebasert NOK skal isolert sett ikke skape en kunstig NAV-endring.

Hvis en ny rapportert cash-anchor ikke har en matching, dokumenterbar valutafordeling, brukes ingen konstruert valutamiks for det nye ankeret. Modellen skal heller nedgradere kvaliteten enn å gjette.

## Presentasjon av NOK, USD og BRL

Frontenden bruker `cash_fx.components` til å vise et estimat på kontantbeholdningen per valuta.

På 2025-ankeret er utgangspunktet nå:

1. USD og BRL fra rapportert valutaeksponering;
2. NOK fra den avstemte residualen;
3. alle tre komponentene summerer til total rapportert cash.

Etter rapportdatoen er faktiske valutavekslinger ikke offentlig kjent. Senere netto kontantendringer må derfor fortsatt behandles som et estimat i presentasjonslaget. Denne usikkerheten gjelder **utviklingen etter ankeret**, ikke klassifiseringen av selve 31.12.2025-ankeret.

## Backtest av valutaeffekt

Backtesten påvirker ikke NAV. Primær fasit er **«effects of exchange rate changes on cash and cash equivalents»** i konsernets kontantstrømoppstilling. Resultatført netto valutaresultat er bare diagnostikk fordi det kan inneholde andre monetære poster enn kontanter.

Historiske valutaankre finnes ved 31.12.2023, 31.12.2024 og 31.12.2025. De eldre 2023/2024-ankrene beholdes foreløpig med `UNALLOCATED` residual for å unngå å omskrive den eksisterende out-of-sample-testen i denne endringen. Backtestmotoren støtter både eksplisitt `NOK` og eldre `UNALLOCATED`; begge holdes som NOK-verdi under selve valutaeffektberegningen, men provenance er forskjellig.

Rapporterte kontrollverdier:

| Periode | Faktisk valutaeffekt på cash | Resultatført netto valutaresultat |
|---|---:|---:|
| 2024 | USD -1,510m | USD -0,178m |
| 2025 | USD +0,867m | USD -1,214m |

Backtesten starter med valutaeksponeringen som var kjent ved inngangen til perioden, legger inn kjente `cash_movements` i opprinnelig valuta og isolerer verdiendringen med historiske ECB-krysskurser frem til sluttdatoen.

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
4. driftskostnadsankeret oppdateres når rapporten gir et bedre observerbart run-rate-grunnlag;
5. cash-FX revalueres bare dersom det finnes en matching kildebasert valutafordeling.

En ny rapport skal ikke arve 2025-valutamiksen som fakta. Dersom rapporten ikke dokumenterer ny fordeling, skal modellen vise lavere dekning/ingen ny FX-justering fremfor å fylle inn manglende informasjon.

## API

```text
GET /api/dashboard/economic
GET /api/dashboard/fx-backtest
```

Economic NAV-endepunktet returnerer blant annet regnskapsmessig FULL NAV, økonomisk NAV, konservativ NAV, økonomisk cash og `cash_fx` med justering, dekningsgrad, kildekvalitet og valutakomponenter.

Hvis FULL og CORE ikke er på samme dato, nødvendige markeds-/FX-input mangler eller driftskostnadsankrene mangler, returneres `ready=false` i stedet for et skjult delestimat.

## Kilder

Primærkildene for valutaankre og rapporterte backtestutfall er **Otello Corporation ASA – Annual Report 2024** og **Annual Report 2025**. Kilde-URL og locator lagres sammen med de kuraterte inputene i source-document provenance. Historiske USD/NOK- og BRL/NOK-kurser kommer fra ECBs daglige referansekurser via EUR-kryss.

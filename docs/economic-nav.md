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

### Prinsipp i NAV-beregningen

```text
USD-komponent → revalueres med USD/NOK
BRL-komponent → rekonstrueres til BRL på ankerdato og revalueres med BRL/NOK
UNALLOCATED   → holdes på ankerverdi i NOK
```

Dermed får vi løpende valutaeffekt der det finnes dokumentasjon, men gjetter ikke at residualen ligger i NOK, USD, BRL eller en annen valuta.

Hvis en ny rapportert cash-anchor ikke har en matching dokumentert valutafordeling, brukes ingen cash-FX-justering for det nye ankeret. Kvaliteten vises eksplisitt i API-et.

### Presentasjonsestimat for NOK, USD og BRL

NAV-siden viser i tillegg et separat **estimat på kontantbeholdningen per valuta**. Dette er et presentasjonslag og endrer ikke CORE NAV, FULL NAV eller økonomisk NAV.

Metoden er:

1. USD- og BRL-komponentene starter på de eksplisitt rapporterte eksponeringene per 31.12.2025.
2. Residualen på USD 2,495m klassifiseres **kun i presentasjonsestimatet** som estimert NOK. Dette er en analytisk slutning, ikke et eksplisitt rapportert NOK-beløp.
3. USD- og BRL-komponentene verdsettes med de samme løpende valutakursene som brukes av det kildebelagte valutaoverlaget.
4. Den resulterende valutamiksen skaleres proporsjonalt slik at summen alltid avstemmer til vist økonomisk kontantbeholdning.
5. Netto kontantendringer etter siste rapporterte valutaanker fordeles dermed proporsjonalt mellom NOK, USD og BRL i presentasjonsestimatet. Faktiske valutavekslinger mellom rapportdatoene er ikke offentlig kjent og modelleres derfor ikke som fakta.

Dette gir en løpende indikasjon på valutaeksponeringen, men sikkerheten faller jo lenger tid som går siden siste rapporterte valutaanker. Grensesnittet viser derfor en egen kvalitetsindikasjon basert på alderen på ankeret.

**Viktig:** Den estimerte NOK-andelen brukes ikke som et nytt kildeanker og får ingen egen valutaeffekt i NAV-beregningen. Den konservative NAV-policyen over er uendret: bare dokumentert USD-/BRL-eksponering revalueres.

## Backtest av valutaeffekt

Valutaestimatet valideres i et separat kontrollag. Backtesten påvirker ikke NAV.

### Historiske ankere

Modellen har kildebelagte valutaankre ved 31.12.2023, 31.12.2024 og 31.12.2025. USD- og BRL-bankinnskudd hentes fra Otellos valutarisikonoter. Differansen mot total rapportert cash lagres som `UNALLOCATED` og behandles som NOK **bare som en testhypotese i backtesten**.

Dette gir to fullførte årsperioder som kan testes uten å bruke sluttårets valutamiks som inngangsdata:

- 2024: 31.12.2023 → 31.12.2024
- 2025: 31.12.2024 → 31.12.2025

### Hva er fasit?

Primær fasit er **«effects of exchange rate changes on cash and cash equivalents»** i konsernets kontantstrømoppstilling.

Resultatført netto valutaresultat er kun en sekundær kontroll. Det kan inneholde valutaeffekter på andre monetære eiendeler og forpliktelser og er derfor ikke direkte sammenlignbart med en modell av bankinnskudd.

For de lagrede testperiodene er de rapporterte kontrollverdiene:

| Periode | Faktisk valutaeffekt på cash | Resultatført netto valutaresultat |
|---|---:|---:|
| 2024 | USD -1,510m | USD -0,178m |
| 2025 | USD +0,867m | USD -1,214m |

I 2024-rapporten presenteres i tillegg USD -0,216m som FX-forskjeller knyttet til endringer i balanseposter. Denne holdes utenfor cash-fasiten.

### Backtestmetode

For hver periode:

1. start med valutaeksponeringen som faktisk var kjent ved inngangen til perioden;
2. rekonstruer BRL-beløpet fra rapportert USD-ekvivalent og historiske USD/NOK- og BRL/NOK-kurser;
3. klassifiser bare residualen som NOK-hypotese;
4. legg inn kjente `cash_movements` i faktisk opprinnelig valuta på strømdatoen, eksempelvis Bemobi-utbetalinger i BRL og OTEC-tilbakekjøp i NOK;
5. før hver kontantstrøm isoleres verdiendringen på den eksisterende valutabeholdningen med historiske ECB-krysskurser;
6. revaluer gjenværende saldo til periodens sluttdato;
7. sammenlign modellert valutaeffekt med rapportert cash-FX-effekt.

Dette er en strengere test enn å bruke sluttårets valutafordeling, fordi modellen ikke får se fasiten på valutamiksen før perioden er ferdig.

Backtesten viser blant annet:

- modellert cash-FX;
- faktisk cash-FX;
- avvik i USD;
- enkel treffgrad;
- om modellen traff riktig fortegn/retning;
- resultatført FX som separat diagnostikk;
- antall kjente kontantstrømmer som ble brukt;
- gap mellom modellert og faktisk slutt-cash som mål på ikke-modellerte strømmer.

Et stort slutt-cash-gap betyr at deler av kontantstrømmen gjennom året ikke er klassifisert i riktig valuta. Det skal tolkes som svakere evidens for valutaestimatet, ikke skjules ved å tvinge modellen til å avstemme.

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

Presentasjonsestimatet for NOK/USD/BRL skal samtidig flyttes til det nye rapportankeret når rapporten gir tilstrekkelig informasjon. Dersom valutaopplysningene er svakere enn ved forrige rapport, skal kvaliteten nedgraderes i stedet for å fylle inn manglende informasjon som fakta.

## API

```text
GET /api/dashboard/economic
GET /api/dashboard/fx-backtest
```

Economic NAV-endepunktet returnerer blant annet:

- regnskapsmessig FULL NAV per aksje;
- økonomisk NAV per aksje;
- konservativ økonomisk NAV;
- rabatt til økonomisk NAV;
- økonomisk cash;
- `cash_fx` med justering, dekningsgrad, kildekvalitet og valutakomponenter;
- regnskapsført og økonomisk opsjonsverdi;
- ekstra opsjonsoverheng;
- driftskostnad siden cash-anker;
- source document IDs/metodikk for kostnadsankrene.

Backtest-endepunktet returnerer periodevise resultater og aggregert feil-/retningsstatistikk. Hvis nødvendige historiske ECB-kurser ikke finnes i databasen, markeres perioden eksplisitt som ikke klar i stedet for å bruke en konstruert kurs.

Frontenden bruker `cash_fx.components` sammen med økonomisk cash til det separate valutaestimatet. Det legges ikke til en ny API-verdi som kan forveksles med et rapportert valutabeløp.

Hvis FULL og CORE ikke er på samme dato, nødvendige markeds-/FX-input mangler eller driftskostnadsankrene mangler, returneres `ready=false` i stedet for et delvis skjult estimat.

## Kilder

Primærkildene for valutaankre og rapporterte backtestutfall er **Otello Corporation ASA – Annual Report 2024** og **Annual Report 2025**. Kilde-URL og locator lagres sammen med de kuraterte inputene i source-document provenance. Historiske USD/NOK- og BRL/NOK-kurser kommer fra ECBs daglige referansekurser via EUR-kryss.

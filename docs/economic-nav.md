# Økonomisk NAV-overlay

## Formål

Dashboardet beholder den validerte `CORE NAV`- og `FULL NAV`-serien uendret. I tillegg vises et separat investorjustert **økonomisk NAV** som gjør to konservative justeringer etter siste rapporterte balanse-/cash-anker:

1. hele økonomiske Black-Scholes-verdien av Otellos kontantoppgjorte opsjonsprogram trekkes fra, ikke bare den regnskapsmessig innregnede delen;
2. løpende driftskostnader estimeres fra siste rapporterte cash-anker frem til NAV-datoen.

Dette er et presentasjons-/analyseoverlay. Det skriver ikke om historiske CORE/FULL-rader og endrer ikke buyback-, cash-, ONA- eller opsjonsmodellen som brukes til regnskapsmessig avstemming.

## Formel

```text
Økonomisk FULL NAV
= regnskapsmessig/modellert FULL NAV
- (økonomisk opsjonsverdi - regnskapsført/modellert opsjonsforpliktelse)
- estimerte driftskostnader siden siste rapporterte cash-anker
```

Det ekstra opsjonsoverhenget kan aldri bli negativt.

## Opsjonsjustering

Den eksisterende opsjonsmodellen beregner allerede:

```text
Black-Scholes-verdi per opsjon × 4,1m opsjoner
```

Dette er programmets modellerte økonomiske bruttoverdi. Den eksisterende FULL NAV trekker bare den delen som er innregnet gjennom modellens recognition/calibration factor, kalibrert mot rapportert forpliktelse på USD 314k per 31.12.2025.

Økonomisk NAV viser derfor separat:

- regnskapsført/modellert opsjonsforpliktelse;
- full økonomisk Black-Scholes-verdi;
- differansen som «ekstra opsjonsoverheng».

## Løpende driftskostnader etter cash-anker

Den ordinære cash-kurven fortsetter å bruke rapportert cash pluss kjente kontantstrømmer. Den endres ikke av dette overlayet.

Økonomisk NAV legger i stedet på en separat kostnadsavsetning fra siste `REPORTED` cash-anker.

### Base – siste halvårs underliggende kostnadsnivå

2H25-rapporten viser underliggende driftskostnader ekskl. aksjebasert kompensasjon på:

- employee benefits: USD 0,596m;
- other operating expenses: USD 0,425m;
- depreciation/amortization: USD 0.

Dette gir USD 1,021m over 184 kalenderdager og brukes som siste observerte kostnadsrun-rate:

```text
USD 1,021m / 184 kalenderdager
≈ USD 5,55k per dag
≈ USD 2,03m annualisert
```

Den daglige USD-run-raten akkumuleres fra siste rapporterte cash-anker og konverteres med siste tilgjengelige USD/NOK-rate innenfor syv kalenderdager før NAV-datoen.

### Konservativ sensitivitet – revidert helår

Primær kontrollkilde er Otello Corporation ASA Annual Report 2025:

`https://otello.cdn.prismic.io/otello/agOFxqYofJOwHJQ4_OtelloCorporationASAAnnualReport2025.pdf`

Den reviderte årsrapporten opplyser at 2025 operating expenses ekskl. aksjebasert kompensasjon var USD 2,641m. Dette brukes som konservativ annualisert kostnadsrun-rate.

Dashboardet viser derfor både:

- **Økonomisk NAV:** siste observerte 2H25 underliggende kostnadsrun-rate, ca. USD 2,03m annualisert;
- **Konservativ NAV:** revidert FY25 driftskost, USD 2,641m annualisert.

Vi bruker driftskostnader direkte i stedet for adjusted EBITDA fordi årsrapporten inneholder annen inntekt som gjør EBITDA mindre egnet som ren kostnadsproxy.

## Renteinntekter

Renteinntekter på kontantbeholdningen estimeres ikke i første versjon av overlayet. Å utelate dem gjør det økonomiske NAV-estimatet bevisst konservativt og unngår å anta fremtidig cash-beholdning og rente uten nytt rapportanker.

## Automatisk reset ved ny rapport

Kostnadsavsetningen starter alltid fra den nyeste raden i `cash_anchors` med `anchor_type='REPORTED'` som ligger på eller før NAV-datoen.

Når en ny Otello-rapport legges inn med et nyere cash-anker:

1. gammel akkumulert kostnadsavsetning stopper;
2. økonomisk cost accrual resettes til null på den nye ankerdatoen;
3. kostnader begynner å akkumuleres på nytt etter det nye ankeret.

Run-raten skal oppdateres når en nyere rapport gir bedre dokumentasjon på underliggende driftskostnader.

## API

Ny read-only kontrakt:

```text
GET /api/dashboard/economic
```

Den returnerer blant annet:

- regnskapsmessig FULL NAV per aksje;
- økonomisk NAV per aksje;
- konservativ økonomisk NAV per aksje;
- økonomisk NAV-rabatt;
- økonomisk cash etter cost accrual;
- regnskapsført og økonomisk opsjonsverdi;
- ekstra opsjonsoverheng;
- kostnad siden siste cash-anker og brukt run-rate;
- datakvalitet/metodikk.

Hvis siste FULL NAV ikke er på samme dato som siste CORE NAV, returnerer overlayet `ready=false` i stedet for å presentere et økonomisk NAV basert på en foreldet FULL-serie.

# Otello opsjonsforpliktelse i FULL NAV

Phase 15.3.2 skiller Otellos kontantoppgjorte opsjonsprogram ut fra øvrige netto eiendeler/-forpliktelser (ONA) og verdsetter forpliktelsen eksplisitt fra tildelingsdatoen 15.09.2025.

Dette er en **FULL NAV-komponent**. CORE NAV og buyback-modellen endres ikke.

## Kildegrunnlag

Primærkilden er Otello Corporation ASA Annual Report 2025, note 4.

Kuraterte kildeinput ligger i:

```text
backend/app/history/data/otello_option_program_2025.json
```

Kildegrunnlaget som modellen bruker:

- 4 100 000 opsjoner ble tildelt 15.09.2025;
- opprinnelig exercise/strike er NOK 12,5637;
- strike skal reduseres for Otello-utdelinger som erklæres og betales etter tildelingen;
- programmet er kontantoppgjort;
- kontantoppgjøret ved utøvelse er knyttet til OTEC-sluttkurs minus gjeldende strike;
- utøvelse er betinget av kvalifiserende salg av Bemobi-aksjer og tilbakeføring av nettoproveny til Otello-aksjonærene;
- det er ingen formell utløpsdato;
- tredjeparts Black-Scholes-verdsettelse brukte tre års løpetid ved tildeling;
- rapportert opsjonsforpliktelse 31.12.2025 var USD 314 000;
- rapporten oppgir Black-Scholes-parametere både ved tildeling og 31.12.2025.

## NAV-dekomponering

Rapportert ONA er fortsatt:

```text
Total assets - cash - Bemobi carrying value - total liabilities
```

Fra opsjonsprogrammet oppstår dekomponeringen:

```text
ONA = base ONA ex option
    + Bemobi distribution receivables
    - option liability
```

Dermed blir:

```text
FULL NAV = CORE NAV + option-aware ONA
```

På 31.12.2025:

```text
reported ONA                 USD 2.974m
reported option liability    USD 0.314m
base ONA ex option           USD 3.288m

3.288m - 0.314m = 2.974m
```

Dette sørger for at den rapporterte balansen fortsatt avstemmer nøyaktig samtidig som opsjonsforpliktelsen kan bevege seg mellom rapportdatoene.

## Daglig mark-to-market

Fra 15.09.2025 beregnes en Black-Scholes-verdi per opsjon med:

- faktisk/siste gyldige OTEC-kurs for datoen;
- gjeldende strike etter eventuelle betalte Otello-utdelinger;
- tid til forventet settlement-dato;
- rapportert/kurert risikofri rente;
- rapportert/kurert volatilitet;
- dividend yield 0, i tråd med kildeinputene.

Den økonomiske bruttoverdien beregnes som:

```text
Black-Scholes value per option × 4.1m options
```

FULL NAV trekker imidlertid **ikke automatisk hele brutto Black-Scholes-verdien**. Modellen estimerer den regnskapsmessige opsjonsforpliktelsen ved å bruke en recognition/calibration factor som avstemmes mot rapportert forpliktelse.

## Recognition factor

På 31.12.2025 kalibreres faktoren slik at:

```text
modeled option liability = audited USD 314k
```

Historisk mellom tildeling og 31.12.2025 rekonstrueres faktoren fra 0 ved tildeling til den rapporterte årssluttverdien.

Etter 31.12.2025 **holdes recognition factor konstant** frem til ny dokumentert informasjon foreligger. Den økes ikke mekanisk med tid fordi programmets exercisability er betinget av salg av Bemobi-aksjer og tilbakeføring av proveny, ikke bare tidsforløp.

Når Otello senere rapporterer en ny opsjonsforpliktelse eller et kvalifiserende Bemobi-salg skjer, skal modellen oppdateres eksplisitt.

## Parametere etter siste rapport

Inntil en nyere rapport gir nye verdsettelsesinput brukes siste rapporterte:

- risikofri rente: 3,9 %;
- volatilitet: 23,4 %.

Forventet settlement-dato er foreløpig 15.09.2028 fordi tredjepartsverdsettelsen ved tildeling brukte tre års løpetid. Dette er **ikke en formell expiry date** og skal erstattes hvis en senere rapport gir et bedre estimat.

## Strike-justering

Etter tildeling søker modellen etter betalte Otello-utdelinger i NOK. Disse reduserer strike fra NOK 12,5637.

En eventuell utdeling på NOK 1 per aksje etter tildeling gir eksempelvis:

```text
12.5637 - 1.00 = 11.5637
```

Lavere strike øker opsjonsverdien, alt annet likt, og dermed også den modellerte forpliktelsen.

## Historisk NAV

Før 15.09.2025 beholdes den gamle historiske ONA-banen uendret.

Fra tildelingsdatoen:

1. base ONA skilles fra opsjonsforpliktelsen;
2. OTEC-kursen brukes i daglig Black-Scholes;
3. opsjonsforpliktelsen trekkes fra ONA;
4. FULL NAV og historisk rabatt bygges på nytt.

Dette betyr at FULL NAV/rabatt fra 15.09.2025 kan avvike fra tidligere beregnet historikk. Det er tilsiktet fordi modellen nå tar hensyn til en tidligere implisitt, men ikke daglig verdsatt, forpliktelse.

## Datakvalitet

Daglige rader får eksplisitt option quality:

- `NONE` – før tildeling;
- `INTERPOLATED_TO_REPORTED` – mellom tildeling og 31.12.2025;
- `REPORTED_CALIBRATED` – rapportdato med eksakt avstemming;
- `FORECAST_MARK_TO_MARKET` – etter siste rapport, med siste dokumenterte parametere.

Alle relevante input lagres i `option_inputs_json` sammen med hash/provenance slik at beregningen kan etterprøves.

## Cloudflare/D1

SQLite-migrasjon `0017_option_liability.sql` og D1-migrasjon `0004_option_liability.sql` legger til de nødvendige feltene. D1 bootstrap/parity inkluderer dem slik at Cloudflare-resultatet fortsatt må være logisk identisk med referanseimplementasjonen.

D1-migrasjon `0001` er nå en frosset baseline. Nye felter legges til med nummererte additive migreringer; eksisterende remote D1 skal aldri kreve at `0001` omskrives.

# Revisjon av eksterne API-kall

Dato: 7. september 2026

## Omfang og metode

Revisjonen omfatter alle direkte eksterne HTTP-kall i `cloudflare/src` og
`backend/app`. NewsWeb, Euronext, B3, Yahoo Finance, Norges Bank, ECB, CVM,
Bemobi IR, Life360 IR/LSEG, BCB SGS/Focus, Investing.com og medie-RSS ble fulgt
fra HTTP-respons gjennom parsing, validering, lagring, fallback og kildevisning.

Kontrollene dekket timeout, HTTP 429 og 5xx, tom respons, ugyldig JSON,
manglende felt, endret datatype, delvis respons, gamle data, duplikater,
pagination, retries og rate limits. Eksisterende størrelsesgrenser, guards,
planlagte nye forsøk, databasekontrakter og kallende kode ble kontrollert for å
forsøke å motbevise kandidatene.

## Bekreftet feil og rettelse

### Ugyldig BCB Focus-konvolutt ble merket som vellykket delkall

**Klassifisering:** CONFIRMED BUG. **Confidence: 97 %.**

En realistisk respons fra OData-tjenesten ved en mellomliggende feil eller endret
kontrakt er HTTP 200 med en feilkonvolutt eller delvis `value`-liste, for eksempel:

```json
{"error":{"message":"Too many requests"}}
```

eller:

```json
{"value":[{"Indicador":"IPCA"},"truncated"]}
```

HTTP-status, responsgrense og JSON-parsing godkjente svaret. `_latest_rows`
gjorde deretter manglende eller feiltypet `value` om til en tom liste og fjernet
ugyldige rader. Kalleren satte derfor det aktuelle Focus-delkallet til
`ready: true`, selv om leverandørsvaret var ugyldig eller delvis. Ingen slike
rader ble lagret som konsensustall, og den samlede `ready`-vakten krevde minst én
matchet forventning. Disse vaktene motbeviste kandidaten om feil finansielle
verdier, men ikke at en mislykket eller delvis operasjon ble merket vellykket i
kildestatusen som dashboard-API-et eksponerer.

Rettelsen krever at OData-svaret er et objekt med en `value`-liste og at alle
rader er objekter. Et tomt, men gyldig `value`-resultat er fortsatt tillatt.
Ugyldige og delvise konvolutter går nå til eksisterende kontrollerte feilsti per
endepunkt. Regresjonstesten dekker feilkonvolutt, endret datatype og delvis liste.

Vurdering før rettelsen:

1. Situasjonen ble ikke håndtert korrekt.
2. Koden feilet ikke kontrollert, men rapporterte delkallet som klart.
3. Ingen feil konsensusverdi ble lagret eller presentert.
4. Koden kunne ikke bli stående og hadde ingen unødvendig retry-løkke.
5. En mislykket eller delvis operasjon kunne markeres som vellykket.

## Øvrige resultater

- Transportfeil, 429 og 5xx gir kontrollert jobb- eller kildesvikt. Siste gode
  data beholdes der fallback finnes. Manglende generell lokal retry er fortsatt
  en forbedringsmulighet, ikke en dokumentert produksjonsfeil.
- Markedsdata og dokumentkilder validerer sentrale identiteter, datoer, tall,
  filformat og responsstørrelse før lagring. Ingen annen vei til feil lagrede
  eller feilaktig ferske data ble bekreftet.
- NewsWeb håndterer overflow med avgrenset splitting og deduplisering. Filbaserte
  dags- og årsarkiver har ikke API-pagination.
- Focus bruker `$top=1200` uten å følge en eventuell neste-side-lenke. De korte,
  filtrerte vinduene dokumenterer fortsatt ikke reell avkorting. Dette er en
  **PLAUSIBLE RISK**, ikke en bekreftet feil.
- Alle observerte retries og planlagte gjenkjøringer er avgrenset. Ingen fastlåst
  eller uendelig retry-løkke ble funnet.

## Gjenværende usikkerhet

Feilscenariene ble gjenskapt med lokale testresponser; eksterne tjenester ble
ikke med vilje belastet eller provosert til feil. Leverandørkontrakter og botvern
kan endres. Pagination for BCB Focus bør vurderes på nytt dersom søkevinduene
eller antallet indikatorer økes.

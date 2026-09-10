# Revisjon av eksterne API-kall

Dato: 10. september 2026

## Omfang og metode

Revisjonen omfatter alle direkte eksterne kall i `cloudflare/src` og
`backend/app`. NewsWeb, Euronext, B3, Yahoo Finance, Norges Bank, ECB, CVM,
Bemobi IR, Life360 IR/LSEG, BCB SGS/Focus, Investing.com, medie-RSS og den nye
Workers AI-integrasjonen ble kontrollert. Kallene ble fulgt gjennom transport,
HTTP-status, responslesing, parsing, validering, lagring, fallback og
presentasjon. Endringer siden revisjonen 7. september ble gjennomgått særskilt.

Kontrollene dekket timeout, HTTP 429 og 5xx, tom respons, ugyldig JSON,
manglende felt, endret datatype, delvis eller gammel respons, duplikater,
pagination, retries og rate limits. Eksisterende tester, størrelsesgrenser,
statusmarkering, databasekontrakter og kallende kode ble brukt for aktivt å
forsøke å motbevise kandidatene.

## Bekreftet feil og rettelse

### Workers AI kunne få en ugyldig oppsummering lagret som klar

**Klassifisering:** CONFIRMED BUG. **Confidence: 98 %.**

Workers AI returnerer modellgenerert tekst, selv om instruksjonen ber om JSON.
En realistisk respons med endret datatype er derfor:

```json
{"title":["Styreprotokoll"],"summary":null}
```

Responsen var gyldig JSON og passerte derfor `json.loads`. Listen og
nullverdien ble deretter konvertert til tekstene `['Styreprotokoll']` og `None`.
Koden genererte en PDF, lagret objektet, satte både oversettelse og oppsummering
til `READY`, og nyhets-API-et brukte disse tekstene som overskrift og sammendrag.
Dermed ble en mislykket deloperasjon markert som vellykket, og ugyldige data
kunne presenteres for brukeren.

Forsøket på å motbevise funnet viste at manglende felter og ugyldig JSON allerede
gikk til den kontrollerte feilstien, og at tomt toppnivåsvar ble avvist av
provideren. Disse vaktene kontrollerte imidlertid ikke datatypen eller innholdet
i de to påkrevde feltene. Databasen har heller ingen kontrakt som hindrer de
tekstkonverterte verdiene.

Rettelsen krever nå et JSON-objekt med to ikke-tomme tekstfelt. Feil datatype,
null, tom tekst, manglende felt og feil toppnivå går til den eksisterende
kontrollerte `FAILED`-statusen før PDF eller sammendrag lagres. En regresjonstest
gjenskaper både liste i `title` og null i `summary`.

Vurdering før rettelsen:

1. Situasjonen ble ikke håndtert korrekt.
2. Koden feilet ikke kontrollert.
3. Ugyldig overskrift og sammendrag kunne lagres og presenteres.
4. Koden ble ikke stående og opprettet ingen ekstra retry-løkke.
5. Den ugyldige oppsummeringen ble markert som `READY`.

## Øvrige resultater

- Transportfeil, 429 og 5xx stopper den aktuelle jobben eller blir isolert som
  kildefeil. Avgrensede retries og senere planlagte kjøringer ble kontrollert;
  ingen uendelig eller unødvendig retry-løkke ble funnet.
- Tomme, ugyldige og delvise responser fra finansielle hovedkilder kontrolleres
  mot identitet, dato, struktur og tall før lagring. Ingen annen vei til feil
  lagrede verdier eller falsk ferskhetsstatus ble bekreftet.
- NewsWeb håndterer avkorting med avgrenset splitting og deduplisering.
  Dags- og årsarkivene er filbaserte og har ikke API-pagination.
- BCB Focus har fortsatt `$top=1200` uten å følge en eventuell neste-side-lenke.
  Dagens korte, filtrerte vinduer viser ikke faktisk avkorting. Dette er en
  **PLAUSIBLE RISK**, ikke en bekreftet produksjonsfeil.
- Enkelte klienter mangler lokal retry eller bruk av `Retry-After`, men feiler
  kontrollert og prøves igjen ved senere planlagt kjøring. Dette er en
  **IMPROVEMENT**, ikke en dokumentert feil.

## Gjenværende usikkerhet

Eksterne tjenester ble ikke med vilje belastet eller provosert til feil.
Feilresponsene ble i stedet gjenskapt lokalt. Leverandørkontrakter, botvern og
Workers AI-feilformater kan endres. Focus-pagination bør vurderes på nytt dersom
søkevinduene eller antallet indikatorer økes.

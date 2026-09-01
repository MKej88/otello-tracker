# Revisjon av eksterne API-kall

Dato: 1. september 2026

## Omfang og metode

Revisjonen omfatter alle direkte eksterne HTTP-kall i `cloudflare/src`. Interne
nettleserkall til egen `/api` er ikke tredjepartsintegrasjoner. Kallene og deres
kallende jobber ble fulgt gjennom HTTP-status, avgrenset responslesing, parsing,
validering, lagring, cache/fallback og presentert kildestatus. Eksisterende tester
og de tidligere revisjonene ble kontrollert for å forsøke å motbevise kandidatene.

Følgende kilder ble gjennomgått: NewsWeb, B3, Yahoo Finance, Euronext, Norges Bank,
CVM, Bemobi IR, Life360 IR/LSEG, BCB SGS/Focus og Investing.com. Scenariene var
timeout, 429, 5xx, tom respons, ugyldig JSON, manglende felt, endret datatype,
delvis eller gammel respons, duplikater, pagination, retry-løkker og rate limits.

## Bekreftet feil og rettelse

### HTTP 200 med blokkeringsside fra Investing.com ble regnet som en klar side

**Klassifisering:** CONFIRMED BUG. **Confidence: 96 %.**

En realistisk respons fra et CDN eller botvern er HTTP 200 med for eksempel:

```html
<html><body>Access denied</body></html>
```

Responsen passerer HTTP-status- og størrelseskontrollen. Parseren finner ingen
kalenderrader og returnerte tidligere en tom liste. Samleren la likevel siden i
`pages`, økte `pages_ready` og lot dashboardet oppføre Investing.com som brukt
kilde. Ingen uriktige konsensustall ble lagret, men en mislykket kildelesing ble
presentert som en vellykket side. `ready` forble `false`, så eksisterende guard
mot å hevde at hendelsesdata var klare motbeviste den alvorligere kandidaten om
feil finansielle verdier, men den motbeviste ikke den uriktige kildeangivelsen.

Rettelsen avviser en side uten én eneste gyldig kalenderrad som en kontrollert
kildefeil. Feilen isoleres fortsatt per side, eksisterende data beholdes, og det
legges ikke til retry. Regresjonstesten gjenskaper en HTTP 200-lignende
blokkeringsside og kontrollerer at `pages_ready` er null og feilen er synlig.

Vurdering før rettelsen:

1. Situasjonen ble ikke håndtert korrekt.
2. Koden feilet ikke kontrollert, men registrerte siden som lest.
3. Ingen finansielle verdier ble forfalsket eller lagret, men kilden kunne vises
   feilaktig som brukt.
4. Koden kunne ikke bli stående og hadde ingen retry-løkke.
5. En mislykket side kunne delvis markeres som vellykket via `pages_ready`.

## Øvrige resultater

- HTTP-feil og transportfeil stopper kallet eller isoleres som kildefeil. Lokale
  retries er avgrenset; ingen uendelig retry-løkke ble funnet.
- Finansielle hovedkilder har struktur-, identitets-, dato- og tallvalidering før
  lagring. Tom, ugyldig eller delvis respons feiler kontrollert der kompletthet er
  nødvendig.
- Siste gode data beholdes ved leverandørfeil og ledsages av kilde-, alder- eller
  jobbstatus. Ingen ny vei som merker gamle verdier som ferske ble bekreftet.
- NewsWeb deler overflow-vinduer og dedupliserer meldings-ID-er. Filendepunktene er
  komplette dags-/årsarkiver. BCB Focus bruker et tak på 1200 rader uten `nextLink`,
  men dagens korte og filtrerte vinduer dokumenterer ikke faktisk avkorting; dette
  forblir en **PLAUSIBLE RISK**, ikke en produksjonsfeil.
- Flere klienter retryer ikke 429/5xx lokalt, eller tolker ikke `Retry-After`.
  Planlagte kjøringer prøver senere, feilstatus er synlig og siste gode data
  beholdes. Uten dokumentert datatap eller fastlåsing er dette en **IMPROVEMENT**,
  ikke en bekreftet feil, og det er derfor ikke lagt til generell retry.

## Gjenværende usikkerhet

Revisjonen bruker falske responser og lokale tester; leverandørene ble ikke belastet
med feilprovokasjon. Upstream-kontrakter og botvern kan endres. Særlig BCBs
`nextLink` bør vurderes på nytt dersom datovinduene eller antall indikatorer økes.

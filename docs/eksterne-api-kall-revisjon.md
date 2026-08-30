# Revisjon av eksterne API-kall

Dato: 30. august 2026

## Omfang og metode

Revisjonen dekker kallene fra Python-koden i `backend/app` og `cloudflare/src`.
Frontend-kall til vår egen Worker er ikke regnet som eksterne datakilder. Jeg gikk
gjennom nedlasting, tolking og lagring for hver kilde og vurderte timeout, HTTP 429,
HTTP 5xx, tom respons, ugyldig JSON, manglende felt, endret datatype, delvis respons,
gamle data, duplikater, paginering, retry-løkker og rate limits.

Vurderingene nedenfor bruker disse korte resultatene:

- **Korrekt:** Svaret valideres, eller situasjonen er uttrykkelig støttet.
- **Kontrollert feil:** Kjøringen stopper uten at det dårlige svaret lagres. Neste
  planlagte kjøring kan prøve på nytt.
- **Beholder siste gode:** Feilen eksponeres, mens allerede lagrede data beholdes.
- **Reelt funn:** En test kunne gjenskape risiko for feil data eller datatap.

## Resultat per kilde

| Kilde | Kall og data | Nettverksfeil, 429 og 5xx | Responsvalidering | Integritet, alder og duplikater | Vurdering |
|---|---|---|---|---|---|
| NewsWeb | Lister, meldinger og PDF-vedlegg | Backend har eksplisitt timeout. Worker lar Fetch/Workflow avbryte kallet. HTTP-feil stopper kjøringen. Ingen lokal retry-løkke. | JSON, meldings-ID, utsteder, marked, meldingstekst og PDF-signatur valideres. Overflow deles i mindre datovinduer. | Meldinger dedupliseres på ID, og korrigerte meldinger utelates. | **Reelt funn rettet:** Manglende `messages`, manglende `overflow`, `null` eller tekst i stedet for boolsk verdi ble tidligere tolket som et gyldig, tomt/ikke-paginert svar. Det kunne skjule meldinger. Nå feiler både backend og Worker kontrollert. |
| Norges Bank | BRL/NOK og USD/NOK SDMX-JSON | HTTP-feil stopper nedlasting; backend bruker timeout. Ingen tett retry-løkke. | Struktur, observasjoner, datoer og tall tolkes og valideres før lagring. | Oppdateringen bruker kilde/dato som identitet og har ferskhetskontroll i visningen. | **Korrekt / kontrollert feil.** |
| ECB | Valutakurser via Norges Bank-oppsettet | Samme avgrensede nettverksmønster; ingen egen endeløs retry. | Tomme eller ugyldige observasjoner avvises. | Datoankere hindrer at en vilkårlig eldre observasjon presenteres som dagens kurs. | **Korrekt / beholder siste gode.** |
| Banco Central do Brasil (SGS og Focus) | Makroserier og forventninger | HTTP-feil stopper enkeltkilden; dashboardet kan markere delresultat som utilgjengelig. Ingen lokal retry-løkke. | JSON-type, gyldige rader, datoer og numeriske verdier kontrolleres. | Kildedato følger resultatet. Delkilder samles med eksplisitt feilstatus i stedet for oppdiktede nullverdier. | **Korrekt / kontrollert delvis respons.** |
| B3 quote og Yahoo Finance | BMOB3 intradag og Life360 historikk | Statusfeil avvises. Yahoo prøver maksimalt to alternative verter, én gang hver; dette er en avgrenset fallback, ikke en retry-løkke. | JSON-struktur, symbol, valuta, tidsstempel og priser valideres. Tomme datasett avvises. | BMOB3 avviser utdaterte kurser; upsert/dokumentnøkler håndterer duplikater. | **Korrekt.** 429 kan gi ett kall til alternativ Yahoo-vert, deretter kontrollert feil; ingen unødvendig vedvarende retry. |
| B3 COTAHIST | Daglig ZIP/faste poster | Backend har timeout, statusfeil feiler kontrollert. Kandidatdatoer er et begrenset søk etter siste handelsdag. | ZIP, filformat, symbol, dato og pris valideres. | Dato og kilde brukes ved lagring; ingen eldre kandidat merkes som nyere dato. | **Korrekt.** |
| Euronext | Forsinket OTEC-kurs og handelsfiler | Timeout/statusfeil stoppes. Recovery henter en avgrenset fil; ingen endeløs retry. | ZIP/CSV, kolonner, instrument, handelstid og numeriske felt kontrolleres. HTML i stedet for data avvises. | Handler har stabile identiteter og dedupliseres. Utvalg og recovery dekker leverandørens filbaserte «paginering». | **Korrekt.** |
| CVM | IPE-, ITR- og DFP-ZIP-er | Timeout/statusfeil stoppes. Årsløkkene er endelige og rapporterer feil i stedet for å spinne. | ZIP/CSV, nødvendige kolonner, selskap og perioder kontrolleres. | Dokumenthash/ekstern ID og rapportperiode hindrer duplikater og eldre rapporter fra å bli nye fakta uten proveniens. | **Korrekt / kontrollert feil.** |
| Bemobi IR, XP og MarketScreener | HTML og rapportfiler | HTTP-feil stoppes; responsstørrelse er begrenset. Et begrenset antall kjente sider/filer prøves. | Innholdstype/signatur, HTML-funn og påkrevde fakta valideres før publisering. | Nyere publiseringsdato prioriteres, og eldre webfakta får ikke overskrive nyere fakta. | **Korrekt / beholder siste gode.** |
| Life360 IR/LSEG | Historisk pristabell fra IR-side | HTTP-feil stoppes, uten lokal retry-løkke. | Tabellen må inneholde gyldige datoer, priser og valuta. Tom/forandret HTML feiler. | Maksimal kursalder håndheves for NAV-ankere; dato/kilde håndterer duplikater. | **Korrekt / kontrollert feil.** |

## Bekreftet feilscenario og rettelse

NewsWeb bruker `overflow` for å fortelle at en liste er avkortet og må deles i
mindre datovinduer. Før rettelsen gjorde koden følgende:

- manglende eller `null` i `messages` ble gjort om til en tom liste;
- manglende `overflow` ble gjort om til `False`;
- teksten `"false"` ble gjort om til `True`, fordi en ikke-tom tekst er sann i
  Python.

Dette er realistiske delvise eller typeendrede API-svar. De to første variantene
kunne presentere «ingen meldinger» selv om svaret var ufullstendig. Den siste kunne
starte unødvendig oppdeling av datovinduet og til slutt feile med overflow på én dag.

En parameterisert pytest-test med alle tre svarvariantene feilet tre ganger mot
gammel kode. Parseren krever nå at `messages` faktisk er en liste, at hvert element
er et objekt, og at `overflow` faktisk er en boolsk verdi. Dermed blir det ingen
lagring eller presentasjon basert på et tvetydig svar, og neste planlagte kjøring kan
forsøke på nytt.

## Retry- og rate-limit-konklusjon

Ingen av de gjennomgåtte klientene har en ubegrenset lokal retry-løkke. De få
fallbackene går over en fast liste av verter, datoer eller filer. HTTP 429 og 5xx
behandles hovedsakelig som midlertidige, kontrollerte feil og overlates til neste
planlagte kjøring/Workflow-forsøk. Det betyr at systemet ikke hamrer leverandøren,
men kan beholde siste gode data frem til en senere vellykket kjøring. Der siste gode
data vises, følger kildedato eller ferskhetsstatus med; de undersøkte flytene lager
ikke et nytt observasjonstidspunkt fra et mislykket API-svar.

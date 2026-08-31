# Audit av data-ferskhet og provenance – 31. august 2026

## Formål og metode

Auditen undersøker om en riktig formatert verdi kan se nyere eller sikrere ut enn
datagrunnlaget tillater. Gjennomgangen følger verdier fra ekstern kilde, via
kildetid og hentetid, effektiv dato, D1-lagring og hot-cache, til API og visning.

Et kandidatfunn regnes bare som en feil når en test eller en entydig kontrakt viser
avviket. At børsdata står stille i helg, eller at et eksplisitt merket estimat bruker
siste kjente verdi, er ikke i seg selv en feil.

## Kritiske dataspor

| Datasett | Kilde og kildetid | Hentetid, effektiv dato og lagring | Cache, fallback og presentasjon | Vurdering |
| --- | --- | --- | --- | --- |
| OTEC, BMOB3 og LIF-kurser | Kilde identifiseres i `sources`; `trading_date` er markedsdato og `observed_at` er observasjonstid. | `market_prices` skiller `observed_at`, `trading_date` og `fetched_at`. | NAV har sju dagers lookback. Dashboardet viser komponentdatoer og markerer `MIXED`, `STALE` eller `UNKNOWN`; kurspanelet viser kursdato og kilde. | Kontrakten tillater siste handelsdag i helg. Ingen bekreftet feil. |
| BRL/NOK og annen FX | Norges Bank foretrekkes foran ECB; `observed_at` bærer rentedato. | `fx_rates` har egen `fetched_at`; NAV velger seneste rentedato innen sju dager. | Komponentdato og blandede markedsdatoer eksponeres. | Ulike kilder har samme dagssemantikk i utvalget. Ingen bekreftet feil. |
| Bemobi-beholdning | Rapportdokument med `effective_from`/`effective_to`. | Effektiv-datert i `bemobi_holdings`, ikke datert med hentetid. | Eierandel skjules som aktuell etter 180 dager og merkes `STALE_REPORTED`. | Eksplisitt stale-kontrakt. Ingen bekreftet feil. |
| Aksjeantall og tilbakekjøp | Kildedokument og handelsdato. | Effektiv dato lagres separat; NAV flagger mulig utdatert aksjeantall når kjøp har skjedd etter ankeret. | Kilde, effektiv dato og om tallet faktisk inngår i NAV returneres. | Ingen bekreftet feil. |
| Kontanter og andre netto eiendeler | Rapportanker med kildedokument; senere kjente kontantstrømmer har hendelsesdato. | Ankerdato og estimeringsdato er separate, og metode/kvalitet lagres i snapshot-komponentene. | Presenteres som estimat, ikke som ny rapportert saldo. | Tillatt videreføring er tydelig. Ingen bekreftet feil. |
| NAV-snapshots | Avledet fra de daterte komponentene. | `as_of_at` er effektiv markedsdato; `created_at` er faktisk beregningstid. | Persistiert hot-snapshot har egen `generated_at` og 90 minutters grense; CDN kan i tillegg bruke eksplisitt `stale-while-revalidate`. | Én bekreftet feil, beskrevet under. |

## Bekreftet feil: cachebygging gjorde gammel NAV-beregning «ny»

### Forventet freshness-kontrakt

`economic.calculated_at` skal være tidspunktet NAV-verdien faktisk ble beregnet,
slik det kommer fra `nav_snapshots.created_at`. Cachetidspunktet skal ligge separat i
hot-snapshotets `generated_at`. Å bygge cache på nytt er ikke en ny beregning av den
lagrede NAV-raden.

### Realistisk scenario

1. Siste NAV-rad ble beregnet 29. august kl. 18:15 UTC.
2. En full refresh 31. august kl. 10:00 UTC bygger hot-snapshot på nytt, men
   datagrunnlaget gir fortsatt den samme NAV-raden.
3. Cachebyggeren overskrev tidligere `economic.calculated_at` med kl. 10:00.

### Hva brukeren faktisk ville se

Forsiden viste den gamle, plausible NAV-verdien sammen med «Sist oppdatert» 31.
august kl. 10:00. Den effektive datoen kunne finnes andre steder, men det konkrete
ferskhetssignalet ved verdien oppga cachetid i stedet for beregningstid.

### Forsøk på å motbevise funnet

Hot-snapshotet har en 90-minutters aldersgrense, så en gammel cachefil blir ikke brukt
ubegrenset. Dette avkrefter likevel ikke feilen: en ny cachefil kunne produseres fra
en eldre NAV-rad og nullstilte dermed cachealderen uten å fornye verdien. At
`generated_at` finnes i bootstrap-metadata hjelper diagnostikk, men erstatter ikke
betydningen av feltet som brukergrensesnittet kaller «Sist oppdatert».

### Reproduksjon og retting

En regresjonstest bygger et snapshot med beregningstid 29. august og cachetid 31.
august. Kontrakten krever at begge tidene bevares i hvert sitt felt. Cachebyggeren
overskriver derfor ikke lenger `calculated_at`. Snapshotnøkkel og versjon er økt, slik
at eldre cacheinnhold med feil tidssemantikk ikke kan serveres etter utrulling.

## Kandidater som ikke ble bekreftet

### Helg og helligdag

Markedsdata velges på `trading_date <= as_of_date` med en avgrenset lookback. En
fredagskurs på lørdag er forventet, og komponentdatoen følger med. Oslo-lukketid
konstrueres med `Europe/Oslo`, som håndterer sommertid. Det ble ikke påvist at UTC
flytter handelsdatoen i presentasjonen.

### Mislykket refresh og siste gode verdi

Klienten beholder siste gode svar ved nettverksfeil, men viser samtidig «Viser siste
gode data» eller «Viser sist hentet» i de aktuelle oversiktene. Dette er en eksplisitt
fallback, ikke dokumentasjon på at verdien er fersk. Ingen kontraktsbrudd ble
bekreftet.

### Nyere verdi overskrevet av eldre verdi

Markeds- og FX-rader har unike nøkler som inkluderer kildens observasjonstid, mens
lesing sorterer på markeds-/rentedato før intern rad-ID. Gjennomgangen fant ingen
reproduserbar sti der en eldre datodatering blir valgt foran en nyere datodatering.

## Rest-risiko og anbefalt kontrakt

Kurspanelet viser dato og kilde, men har ingen absolutt «for gammel»-grense på selve
API-svaret. Dette er ikke bekreftet som feil fordi illikvide instrumenter og
markedsstengte dager legitimt kan ha gammel siste handel. Produktet bør dokumentere
separate grenser per marked før en slik grense innføres; ellers kan et varsel bli mer
misvisende enn verdien det skal forklare.

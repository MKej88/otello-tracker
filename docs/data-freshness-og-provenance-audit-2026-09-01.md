# Audit av data-ferskhet og provenance – 1. september 2026

## Omfang og beviskrav

Auditen følger kritiske verdier fra kilde og kildetid, via hentetid, effektiv
dato, lagring, cache og fallback, til API og presentasjon. En plausibel gammel
verdi er ikke automatisk feil: siste handelsdag i helg og tydelig merkede
estimater er tillatt produktatferd.

Et kandidatfunn er bare bekreftet når en test kan gjenskape avviket eller en
eksplisitt kontrakt brytes. Gjennomgangen omfatter Python-backend, Python Worker,
D1-skjema og presentasjonskontraktene som Python-API-et leverer.

## Kritiske dataspor

| Datasett | Kilde og source timestamp | Hentetid, effektiv dato og lagring | Cache, fallback og presentasjon | Resultat |
| --- | --- | --- | --- | --- |
| OTEC, BMOB3 og LIF | Kilden ligger i `sources`; `trading_date` er handelsdato og `observed_at` er markedsobservasjonen. | `market_prices` har separat `fetched_at`. NAV leser siste gyldige handelsdato i et avgrenset vindu. | Kursdato, kilde og kvalitet følger API-verdien. NAV eksponerer komponentdatoer og `ALIGNED`, `MIXED`, `STALE` eller `UNKNOWN`. | Ingen ny bekreftet feil. Fredagskurs i helg er tillatt. |
| BRL/NOK og annen FX | Norges Bank prioriteres på samme rentedato; ECB er reservekilde. `observed_at` bærer rentedato. | `fx_rates.fetched_at` er hentetid og brukes ikke som markedsdato. | NAV viser rentedato og markerer blandede komponentdatoer. Sju dagers søkevindu er eksplisitt. | Ingen bekreftet feil. |
| Brasil-makro og Focus | BCB/IBGE/Investing.com identifiseres per delkilde. Hver observasjon, publisering eller forventning har egen dato. | Data hentes ved visning; siste gode Focus-/hendelseskonsensus kan lagres i `runtime_state`. `as_of_date` avgrenser hvilke rader som kan brukes. | Delkildefeil vises i `source_status`. Cachefallback merkes som siste gode og leverandør/kvalitet følger forventningen. | Én bekreftet tidssonefeil, rettet nedenfor. |
| Bemobi-beholdning og rapportfakta | Rapportdokument og publiseringsdato er provenance; `effective_from`/`effective_to` styrer gyldighet. | Effektiv dato er skilt fra hentetid i de daterte tabellene. | Gammel rapportert eierandel skjules som aktuell etter 180 dager og får `STALE_REPORTED`. | Eksplisitt stale-kontrakt; ingen bekreftet feil. |
| Aksjeantall og tilbakekjøp | Offisiell melding/dokument og handelsdato. | Aksjeantall er effektivdatert; handler og kumulative verdier lagres med dato og kilde. | NAV markerer aksjeantallet som mulig utdatert når nyere tilbakekjøp kan ha endret det. | Ingen bekreftet feil. |
| Kontanter, andre netto eiendeler og opsjoner | Rapportanker har dokument og rapportdato; senere bevegelser har hendelsesdato. | Anker, estimeringsdato og beregningstid er separate. | Videreføring presenteres som estimat/metode, ikke som ny rapportert saldo. | Tillatt modellatferd; ingen bekreftet feil. |
| NAV og hot-snapshot | Daterte markeds-, FX- og rapportkomponenter danner NAV. | `as_of_at` er effektiv dato, snapshotets `created_at`/`updated_at` er beregningstid, og hot-cache har egen `generated_at`. | Hot-cache avvises etter 90 minutter. API-et skiller cachekilde fra NAV-ens `calculated_at`. | Tidligere feil der cachetid erstattet beregningstid er rettet og regresjonstestet; ingen ny feil. |

## Bekreftet feil: Brasil-dashboardet kunne bruke morgendagens dato

### 1. Forventet freshness-kontrakt

Når klienten ikke sender `as_of_date`, skal Brasil-dashboardets effektive dato
være dagens kalenderdato i Brasil. UTC er riktig for `generated_at` (teknisk
hentetid), men ikke for den lokale datoen som avgrenser brasilianske kilder og
kalenderhendelser.

### 2. Realistisk scenario

Klokken 22:30 i São Paulo 1. september er klokken 01:30 UTC 2. september.
Den tidligere koden tok `datetime.now(UTC).date()` og satte derfor
`as_of_date=2026-09-02`, selv om den effektive lokale datoen fortsatt var
1. september.

### 3. Hva brukeren/systemet faktisk ville se

API-et returnerte et korrekt formatert `as_of_date` for 2. september. Samme dato
ble sendt som øvre grense til BCB/Focus, valutautvalget og publiseringskalenderen.
Verdiene kunne fortsatt se plausible ut fordi kildene normalt bare returnerte
siste tilgjengelige observasjon, men dashboardet påsto en effektiv dato som ennå
ikke var nådd i kildens marked.

### 4. Forsøk på å motbevise funnet

`generated_at` skal være UTC, og eksplisitt `as_of_date` skal respekteres; ingen av
delene er feil. Det kunne også hevdes at en UTC-dato bare er en teknisk
forespørselsgrense. Dette avkrefter ikke funnet fordi feltet heter `as_of_date`,
returneres som dashboardets effektive dato og gjenbrukes av alle brasilianske
datakilder og kalenderberegninger. São Paulo er dermed riktig datosemantikk.

### 5. Reproduksjon og retting

En deterministisk test setter tiden til `2026-09-02T01:30:00Z` og krever lokal
dato `2026-09-01`. Standarddatoen konverteres nå med `America/Sao_Paulo` før
`.date()` tas. Eksplisitte historiske datoer og UTC-basert `generated_at` er
uendret.

## Kandidater som ble avkreftet eller ikke nådde beviskravet

### Siste gode data etter mislykket refresh

Focus- og hendelseskonsensus kan bruke siste gode D1-verdi, men responsen setter
fallback-/cachemetadata og teksten omtaler siste gode verdi. Markeds- og NAV-data
kan også bli stående etter jobbfeil, men komponentdato og runtime-status endres
ikke til en ny markedsdato. Dette er kontrollert degradering, ikke bekreftet falsk
ferskhet.

### Helg og helligdag

Markedsdata velges på effektiv dato innen avgrensede vinduer. Markedskalendere
brukes ved forventet oppdatering, og en fredagsverdi i helg beholder fredagens
komponentdato. Ingen test viste at helg eller helligdag ga en kunstig handelsdato.

### Eldre verdi overskriver nyere verdi

Pris- og FX-lesing sorterer først på kildens effektive dato og deretter på
kildekvalitet/observasjon og intern ID. Focus-cachen avviser eldre survey-dato ved
konkurrerende skriving. Ingen reproduserbar sti valgte en eldre effektiv verdi som
nyere.

### Absolutt aldersgrense for siste handel

Kurspanelet har ikke én universell maksimal alder. Dette er rest-risiko, men ikke
en bekreftet feil: illikvide instrumenter, ulike børskalendere og markedsstengte
dager gjør en felles grense potensielt misvisende. En produktkontrakt per marked
bør fastsettes før strengere varsling innføres.

# Revisjon av eksterne API-kall

Dato: 31. august 2026

## Omfang og metode

Revisjonen omfatter alle direkte nettverkskall i Python-koden i `backend/app` og
`cloudflare/src`. Interne kall fra nettleseren til `/api/...` er ikke eksterne
leverandørkall og er derfor ikke med. Statiske kilde-URL-er i migreringer og
historikkfiler er heller ikke nettverkskall.

Jeg søkte etter `urlopen`, `fetch` og injiserte `fetcher`-funksjoner, fulgte dataene
fra nedlasting gjennom validering og videre til lagring, og sammenholdt dette med
eksisterende tester. Funn som ble rettet, ble først gjenskapt med en test som bruker
en falsk HTTP-respons. Ingen test kontakter en virkelig leverandør.

Vurderingene nedenfor bruker disse fire spørsmålene:

1. Håndteres situasjonen korrekt?
2. Feiler koden kontrollert?
3. Kan feil data bli lagret eller vist?
4. Kan koden bli stående eller prøve unødvendig mange ganger?

## Bekreftet problem og retting

### NewsWeb kunne godta en ugyldig publiseringstid

Både backend- og Worker-parseren kontrollerte bare at `publishedTime` var en
ikke-tom tekst. En realistisk delrespons som `"ikke-et-tidspunkt"` gikk derfor
videre som om den var gyldig. Verdien brukes til sortering og lagring, så en slik
melding kunne bli plassert feil eller lagret med misvisende tidsdata.

- **Før:** (1) nei, (2) nei, (3) ja, ugyldig tekst kunne brukes som tidspunkt,
  (4) ingen retry-løkke.
- **Gjenskaping:** Tester med en ellers gyldig melding og det ugyldige tidspunktet
  feilet først fordi begge parserne godtok meldingen.
- **Rettet:** Parserne krever nå et ISO 8601-tidspunkt med tidssone. Ugyldig eller
  tidssoneløs tekst gir en kontrollert `ValueError` før sortering eller lagring.
- **Etter:** (1) ja, (2) ja, (3) nei, (4) nei. Det er ikke lagt til retry, siden
  samme ugyldige leverandørsvar ikke blir bedre av et umiddelbart nytt kall.

### MFN-listen for tilbakekjøp kunne godta tom HTTP 200

`backend/app/buybacks/collector.py` henter både MFNs selskapsliste og hver artikkel.
En tom HTTP 200-respons ble tidligere dekodet til en tom tekst. For listesiden ga det
null oppdagede meldinger, og kjøringen fortsatte uten å registrere selve kildefeilen.
Det er realistisk ved feil i mellomlager, proxy eller leverandør.

- **Før:** (1) nei, (2) nei for listesiden, (3) ingen nye feiltransaksjoner ble
  skrevet, men gamle data kunne fremstå som komplett ut fra eksisterende
  dekningskontroller, (4) ingen fastlåst løkke.
- **Gjenskaping:** En falsk respons med bare blanktegn viste at `_fetch` returnerte
  tom tekst. Regresjonstesten krever nå en kontrollert `ValueError`.
- **Rettet:** Tomme svar avvises. Svaret leses samtidig med en grense på 3 MiB, slik
  at en feilaktig eller uventet stor HTML-respons ikke kan bruke ubegrenset minne.
- **Etter:** (1) ja, (2) ja, (3) nei, kjøringen stopper før resultatet behandles som
  en vellykket oppdagelse, (4) nei.

## Resultater per klient

| Klient / ekstern kilde | Timeout, 429 og 5xx | Innhold, skjema og delvis svar | Stale, duplikater og sideinndeling | Samlet vurdering |
|---|---|---|---|---|
| `backend/app/newsweb/client.py` – Oslo Børs NewsWeb | Alle kall har timeout. HTTP-feil bobler kontrollert opp, men klienten gjør ingen lokal retry eller særbehandling av 429. | Størrelsesgrenser, JSON-type, API-status, utsteder, marked, ID, ISO 8601-tidspunkt med tidssone, meldingstekst og PDF-signatur valideres. Tomt/ugyldig/delvis svar lagres ikke. | `overflow` deler datovinduet rekursivt; overflow på én dato stopper kontrollert. Meldings-ID dedupliseres og korrigerte meldinger filtreres. | **Kontrollert feil, lav risiko for feil data.** Manglende lokal retry gir heller manglende oppdatering enn feil lagring. |
| `backend/app/marketdata/b3_cotahist.py` – B3 COTAHIST | Timeout og avgrenset eksponentiell retry. 404 for upublisert dagsfil er forventet. Andre 4xx retries likevel, og 429 respekterer ikke `Retry-After`. | Dagsfil har bytegrense og ZIP-/formatkontroll. Årsfil er med hensikt ubegrenset for historisk bootstrap. Fastbreddeformat, dato og quotation factor valideres. | Ingen sideinndeling i filendepunktet. Importlaget bruker idempotent oppdatering. | **Kontrollert feil.** Kan prøve tre/fire ganger unødvendig ved permanent 4xx; dette skriver ikke feil data og løkken er avgrenset. |
| `backend/app/marketdata/bmob3_feed.py` – B3 webkurs | Timeout og maksimalt tre retries. Alle HTTP-feil behandles likt; `Retry-After` brukes ikke. | Bytegrense, JSON, leverandørstatus, instrument, positiv pris og tidspunkt valideres. Valgfrie felter med endret datatype blir `None`. | Dato og maksimal alder kontrolleres før lagring. Dokumenthash og upsert hindrer skadelige duplikater. | **God databeskyttelse.** Ved 429/permanent 4xx kan den vente noen få sekunder unødvendig, men kan ikke låse seg. |
| `backend/app/marketdata/euronext_delayed.py` – Euronext delayed trades | Timeout, tre avgrensede forsøk, retry bare for 429/5xx og støtte for `Retry-After` med tak på 60 sekunder. | Tom respons, ZIP/CSV-størrelse, påkrevde felt, UTF-8, ISIN, valuta, venue, positive verdier og tidsrekkefølge valideres. | Nyeste handel velges deterministisk. Payload-hash gjør gjentakelse idempotent. Endepunktet er filbasert, ikke paginert. | **Håndteres korrekt og feiler kontrollert.** |
| `backend/app/marketdata/norges_bank_fx.py` – Norges Bank | Timeout; HTTP/transportfeil bobler opp uten lokal retry. Backend-lesingen har ingen egen bytegrense. Worker-varianten har 2 MiB-grense. | JSON, dimensjoner, datatype, dato, positive finite kurser, valutaer og komplette valutadatoer valideres før skriving. | Fast datointervall, ingen pagination. Databasen upserter dato/valutapar. Ferskhet bestemmes av etterspurt intervall og jobbstatus. | **Feiler kontrollert og lagrer ikke delvise data.** En uventet stor backend-respons kan bruke mye minne; ikke rettet fordi samme offentlige, smale serie normalt er liten og ingen konkret hendelse/test tilsier høy risiko. |
| `backend/app/marketdata/ecb_fx.py` – ECB-reservekilde | Timeout; ingen lokal retry og ingen bytegrense. | CSV-header, dato og positive finite kurser valideres. Importlaget avviser tomt svar og datoer som mangler NOK/BRL/USD før transaksjonen starter. | Fast datointervall og idempotente prisnøkler. | **Kontrollert feil, ingen bekreftet feil lagring.** Samme begrunnelse som Norges Bank for at bytegrense ikke ble lagt til nå. |
| `backend/app/bemobi/cvm_ipe.py` – CVM IPE | Timeout og tre avgrensede retries, men også permanente 4xx retries; ingen `Retry-After`. | 50 MiB nedlastingsgrense, ZIP, nøyaktig én CSV og alle påkrevde kolonner valideres. Filteret krever både Bemobi-CNPJ og CVM-kode. | Årsarkiver er ikke paginerte. Ekstern ID inkluderer protokoll, versjon og logisk hash, og seneste versjon skilles fra eldre. | **Kontrollert feil og robust duplikathåndtering.** Noen få unødvendige retries er mulig. |
| `backend/app/buybacks/collector.py` – MFN | Timeout, men ingen lokal retry eller egen 429/5xx-policy. | Etter rettingen avvises tom og for stor HTML. Artikkeltekst krever Oslo Børs-kildemerke og alle finansielle felt før lagring. Feil per artikkel rapporteres separat. | URL-er dedupliseres. Kilden tilbyr liste, ikke dokumentert pagination; dekningsgap vises eksplisitt. | **Det bekreftede tomresponsproblemet er rettet.** Transportfeil stopper kontrollert; artikkelfeil gir delresultat med synlig feilliste. |

## Cloudflare-workerne

Worker-koden bruker plattformens `fetch` mot disse eksterne kildene:

- Oslo Børs NewsWeb (`newsweb_client.py` og jobbene som bruker klienten)
- B3 webkurs, B3 COTAHIST og Yahoo-reservekurs (`bmob3_ingestion.py`,
  `b3_full_refresh.py`)
- Euronext delayed-filer (`otec_ingestion.py`, `otec_activity.py`)
- Norges Bank (`norges_bank_full_refresh.py`)
- CVM IPE og CVM-finansarkiver (`cvm_full_refresh.py`,
  `bemobi_cvm_financials.py`)
- Bemobi IR, resultatdokumenter og XP-forhåndsvisninger (`bemobi_web_refresh.py`)
- Life360 IR/LSEG og Yahoo (`life360_ir_lseg.py`, `life360_market_data.py`)
- Brasil-kalenderens offentlige endepunkter (`brazil_calendar_expectations.py`)
- interne kontrollkall mot egen worker (`brazil_dashboard.py`,
  `otec_workflow_recovery.py`), som er nettverkskall, men ikke tredjepartsdata.

Fellesmønsteret er ett `fetch`-forsøk per kjøring, kontroll av HTTP-status og
avgrenset responslesing for de finansielle hovedkildene. Parserne avviser ugyldig JSON,
manglende nøkkelfelt, endrede datatyper og delvise valutadatoer. Jobbene markerer
`error`, `partial`, `not_available` eller `no_trade` i stedet for å konstruere verdier.
Der gamle data beholdes, eksponerer dashboard-/jobbstatus alder eller degradering.

Det finnes ingen uavgrensede retry-løkker i de gjennomgåtte worker-kallene. De fleste
har med hensikt ingen retry inne i samme kjøring; neste planlagte cron-kjøring blir det
neste forsøket. Det reduserer faren for å forsterke 429. Ulempen er at én kort 5xx kan
utsette oppdateringen til neste kjøring, men dette er en kontrollert tilgjengelighetsfeil,
ikke en vei til feil finansielle data.

## Scenariomatrise

| Scenario | Hva skjer i dag? | Risiko etter revisjonen |
|---|---|---|
| Timeout | Alle identifiserte kall har eksplisitt timeout i backend eller er underlagt worker-runtime. Feilen stopper kallet eller markeres i jobbresultatet. | Manglende/stale oppdatering, ikke oppdiktet verdi. |
| HTTP 429 | Euronext-backend følger `Retry-After`; øvrige klienter feiler eller bruker kort, avgrenset retry. | Enkelte oppdateringer kan utsettes; B3/CVM kan gjøre noen unødvendige forsøk. Ingen evig løkke. |
| HTTP 5xx | Samme som 429, bortsett fra at `Retry-After` normalt mangler. | Kontrollert tilgjengelighetsfeil. |
| Tom respons | Finansielle parsere avviser tomt innhold. MFN-hullet er nå testet og rettet. | Ingen bekreftet vei til ny feil lagring. |
| Ugyldig JSON | `json.loads` eller eksplisitt typekontroll stopper før lagring. | Kontrollert parser-/jobbfeil. |
| Manglende felt | Påkrevde felt/dimensjoner/kolonner valideres. Valgfrie presentasjonsfelt kan bli `None`. | Ingen bekreftet feil finansiell verdi. |
| Endret datatype | Kritiske tall, datoer og samlinger konverteres og valideres; feil stopper. | Kontrollert feil. |
| Delvis respons | Valutakilder krever komplett sett per dato; NewsWeb håndterer overflow; flerårsjobber kan rapportere `partial`. | Delresultat blir merket, eller hele transaksjonen avvises. |
| Gamle data | Intradag B3 sjekker leverandørtid/dato. Andre jobber beholder siste gode data og viser kilde-/jobbstatus. | Gamle data kan fortsatt vises ved leverandørfeil, men de overskrives ikke med en falsk fersk verdi. |
| Duplikater | Meldings-ID, dokumenthash, versjonsnøkler og database-upsert brukes avhengig av kilde. | Gjentatte kjøringer er i hovedsak idempotente. |
| Pagination | NewsWeb-overflow deles til mindre datovinduer. Års-/dagsfiler er komplette filer. Ingen annen gjennomgått kilde annonserer pagination i kontrakten som brukes. | Ingen bekreftet stille avkorting. |
| Retry loops | Alle lokale retries har fast maksimum; workerne bruker normalt neste cron. | Ingen fastlåst løkke. |
| Rate limits | Begrenset samtidighet i NewsWeb-jobber og få planlagte kall. Bare Euronext-backend tolker `Retry-After`. | Lav løkkerisiko; noen klienter kan oppdatere senere enn ønsket. |

## Ikke endret med vilje

Det ble ikke lagt inn generelle retries i alle klienter. En retry er nyttig ved korte
5xx-feil, men kan gjøre 429 verre og gjøre jobbene langsommere. Det finnes allerede
planlagte nye kjøringer og «siste gode verdi»-semantikk. Uten et dokumentert behov per
leverandør ville en felles retry-policy vært defensiv kode uten et bekreftet scenario.

Det ble heller ikke innført streng «må finne minst én melding»-regel for MFN-listen.
En gyldig liste kan faktisk være tom. Bare en tom HTTP-body er entydig feil; derfor er
rettingen begrenset til akkurat det bekreftede scenariet.

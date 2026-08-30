# Audit av eksterne API-kall i Cloudflare-koden

Dato: 2026-08-30

## Omfang og metode

Gjennomgangen dekker produksjonskall fra Python-koden i `cloudflare/src`. Interne kall fra
nettleseren til `/api/*`, statiske kildelenker og utviklingsverktøy er ikke eksterne API-kall.
Kallene ble gruppert etter felles nedlastings- og valideringskode. Feilscenariene ble kontrollert
mot parserne og med isolerte tester/falske responser; ingen ekte leverandør ble belastet.

Vurderingsskala:

- **Korrekt:** responsen valideres og kan ikke lagres som gyldige data.
- **Kontrollert feil:** jobben/kilden merkes mislykket eller beholder siste gode data.
- **Feil data:** responsen kan bli lagret eller vist som om den var gyldig.
- **Unødig retry:** en permanent responsfeil behandles som en midlertidig jobbfeil.

## Kall som er gjennomgått

| Kilde | Klient/flyt | Viktigste responsformat |
| --- | --- | --- |
| Oslo Børs NewsWeb | `newsweb_client.py` og NewsWeb-jobbene | JSON og PDF |
| Banco Central do Brasil (SGS/Focus) | `brazil_dashboard.py`, `brazil_calendar_expectations.py` | JSON/OData |
| Norges Bank EXR | `norges_bank_full_refresh.py` | CSV |
| CVM | `cvm_full_refresh.py`, `bemobi_cvm_financials.py` | ZIP/CSV |
| B3 og Yahoo | `b3_full_refresh.py`, `bmob3_ingestion.py` | ZIP/tekst og JSON |
| Euronext | `otec_ingestion.py`, `otec_activity.py`, `otec_workflow_recovery.py` | JSON/CSV |
| Bemobi IR og offentlige nettsider | `bemobi_web_refresh.py`, `bemobi_ir_refresh.py` | HTML/PDF |
| Life360/LSEG | `life360_market_data.py`, `life360_ir_lseg.py` | JSON/CSV |

## Resultater per feilscenario

### Timeout, HTTP 429 og HTTP 5xx

Alle gjennomgåtte nedlastere lar nettverksfeil/timeout boble opp, og avviser HTTP-responser der
`ok` er falsk før parsing eller lagring. Dermed feiler de kontrollert og lagrer ikke feilsider.
Cloudflare Workflow har endelige tidsgrenser og et begrenset antall retries per steg. Jobbene kan
altså ikke havne i en uendelig retry-loop.

429 behandles på samme måte som øvrige HTTP-feil. Koden leser ikke `Retry-After`, så et workflow-
retry kan komme tidligere enn leverandøren ønsker. Dette er en **begrensning**, men ikke et påvist
data-integritetsproblem: retry-antallet er avgrenset, og data lagres ikke. En generell egen retry-
mekanisme ble derfor ikke lagt til; den ville duplisert Workflow-retries og kunne økt belastningen.

### Tom respons og ugyldig JSON

JSON-klientene bruker størrelsesbegrenset lesing og eksplisitt JSON-parsing. Tomt innhold og
ugyldig JSON gir unntak før lagring. Binære kilder kontrollerer forventet signatur/format (blant
annet PDF og ZIP), mens CSV-parserne krever brukbare rader. Situasjonene håndteres derfor korrekt
eller feiler kontrollert.

### Manglende felt, endret datatype og delvis respons

Parserne avviser i hovedsak feil toppnivåtype, manglende samlinger og rader uten nødvendige
verdier. Delvise makroresultater holdes per kilde, slik at én utilgjengelig serie ikke oppgis som
en ny måling.

**Bekreftet problem:** NewsWeb godtok tidligere en melding uten `publishedTime`, eller et felt med
endret datatype, og konverterte dette til henholdsvis tom tekst eller tekstrepresentasjonen av et
objekt. En slik melding kunne gå videre til ingest med ugyldig publiseringstid. Problemet ble
reprodusert direkte mot parseren (`published_at=''`). Parseren avviser nå manglende, tom og ikke-
tekstlig publiseringstid før noe kan lagres. To regresjonstester dekker både manglende felt og
endret datatype.

Andre valgfrie metadatafelt kan fremdeles mangle. Det er tilsiktet: de brukes ikke som identitet,
tidsstempel eller beløp, og en strengere validering ville kunne forkaste reelle børsmeldinger uten
et konkret dataproblem.

### Gamle/stale data

Dashboardflytene beholder flere steder siste gode verdi når en kilde feiler, i stedet for å
overskrive med en tom respons. Responsene inneholder kilde-/observasjonsdato eller kvalitetsstatus,
slik at gamle data kan merkes. Dette er korrekt fallback-atferd, men betyr at operativ overvåking
må reagere på kildestatus; "siste gode" er ikke det samme som en ny observasjon.

### Duplikater

NewsWeb dedupliserer på `message_id` og utelater meldinger som er markert erstattet av en
korreksjon. Dokument- og markedsdataflytene bruker stabile eksterne id-er, hash eller database-
upsert. Gjentatt workflow-kjøring skal dermed være idempotent. Ingen reproduksjon viste at samme
observasjon kunne lagres som to aktive observasjoner.

### Pagination og avkortede svar

NewsWeb har ingen vanlig sidecursor, men returnerer et `overflow`-flagg. Klienten deler da
søkevinduet rekursivt i ikke-overlappende datointervaller. Hvis selv én dag er full, stopper den
med tydelig feil i stedet for å presentere et ufullstendig resultat. Resultatet dedupliseres etter
sammenslåing.

Focus-kallene er eksplisitt avgrenset med `$top=1200` og korte dato-/indikatorvinduer. API-et gir
ikke i dagens bruk et påvist stille tap, og det ble derfor ikke innført spekulativ OData-paginering.
CVM/B3 års- og dagsfiler er hele filer, ikke paginerte endepunkter.

## Konklusjon

Ett reelt dataintegritetsproblem ble bekreftet og rettet: delvis NewsWeb-respons kunne slippe
igjennom uten gyldig publiseringstid. De øvrige undersøkte scenariene stopper før lagring, bruker
siste gode data med status, eller er avgrenset av Workflow. Det er ikke lagt inn generelle retries,
backoff eller strengere krav uten et realistisk og reproduserbart feilscenario.

# Migreringshistorikk og reserverte numre

Migreringsnumre er en del av databasehistorikken. Et nummer som har vært brukt mot en produksjonsnær eller eksisterende database skal **ikke gjenbrukes**, selv om den tilhørende funksjonen senere fjernes fra kildekoden.

## Aktiv sekvens

### SQLite-referanse

Aktive migreringer i `backend/app/db/migrations/` går per 26.08.2026 til `0026_life360_holding_anchors.sql`.

- `0019` oppretter den kildebelagte tabellen `bemobi_investor_facts`.
- `0020` kobler automatiske Bemobi-fakta til `source_documents`.
- `0021` registrerer Norges Bank som autoritativ valutakilde for direkte BRL/NOK- og USD/NOK-kurser.
- `0022` oppretter historikklagene `bemobi_forward_consensus_snapshots` og `bemobi_consensus_events`.
- `0023` legger til Life360-markedsdata som kildebelagt investorlag.
- `0024` registrerer Life360 IR/LSEG-fallbacken.
- `0025` legger til rapporterte `Investments in other shares` og Life360 rapportanker for Estimert NAV-splitten.
- `0026` oppretter `life360_holding_anchors`, slik at Life360-aksjeantallet er kildebelagt og effektivt datert i stedet for hardkodet i NAV-koden.

### Cloudflare D1

Aktive migreringer i `cloudflare/migrations/` går per 26.08.2026 til `0017_life360_holding_anchors.sql`.

- `0009` oppretter og seeder Bemobi-faktalaget i D1.
- `0010` legger til samme webproveniens som SQLite `0020`.
- `0011` registrerer Norges Bank som samme nye FX-kilde som SQLite `0021`.
- `0012` oppretter og seeder samme Bemobi-konsensushistorikk som SQLite `0022`.
- `0013` legger til samme Life360-markedsdatalag som SQLite `0023`.
- `0014` er en avgrenset datamigrering som setter relevante Otello-resultatmeldinger tilbake til `PARSED` for ny parserkjøring.
- `0015` registrerer Life360 IR/LSEG-fallbacken.
- `0016` legger til rapporterte `Investments in other shares` og in-place backfill av Life360-rapportkurs for eksisterende produksjons-D1.
- `0017` oppretter `life360_holding_anchors` og backfiller 31.12.2025-holdingen når eksisterende produksjons-D1 allerede har Annual Report 2025-kildedokumentet. Fersk bootstrap får holdingsraden fra den deterministiske SQLite-eksporten.

SQLite og D1 skal fortsatt være strukturelt og logisk kompatible og inngår i den deterministiske paritetskontrollen.

## Reserverte, retirerte numre

Aksjonær-/Top 20-funksjonen ble fjernet i PR #95. I forbindelse med denne funksjonen hadde følgende migreringer vært opprettet:

- SQLite: `0018_shareholder_snapshots.sql`
- Cloudflare D1: `0008_shareholder_snapshots.sql`

Filene er ikke lenger del av aktiv kodebase, men nummerene regnes som historisk brukt og skal ikke tas i bruk til noe annet.

**Neste nye migrering skal minst være:**

- SQLite: `0027_...`
- Cloudflare D1: `0018_...`

## Regel for nye migreringer

1. Ikke endre innholdet i en migrering som kan være kjørt i en eksisterende database.
2. Ikke gjenbruk et retirert nummer.
3. Legg nye endringer i en ny, additiv og bakoverkompatibel migrering.
4. Husk at Worker-rollback ikke ruller tilbake D1-migreringer.
5. Bruk D1 Time Travel ved behov for databasegjenoppretting, ikke destruktiv omskriving av migreringshistorikken.

PR #95 fjernet selve aksjonærfunksjonen uten å kjøre destruktive `DROP TABLE`-operasjoner mot eksisterende produksjons-D1. Eventuelle gamle tabeller kan derfor finnes i en eldre database uten at de brukes av dagens applikasjon.

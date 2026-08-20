# Migreringshistorikk og reserverte numre

Migreringsnumre er en del av databasehistorikken. Et nummer som har vært brukt mot en produksjonsnær eller eksisterende database skal **ikke gjenbrukes**, selv om den tilhørende funksjonen senere fjernes fra kildekoden.

## Aktiv sekvens

### SQLite-referanse

Aktive migreringer i `backend/app/db/migrations/` går per 20.08.2026 til `0017_option_liability.sql`.

### Cloudflare D1

Aktive migreringer i `cloudflare/migrations/` går per 20.08.2026 til `0007_reconcile_2025_cash_fx_nok.sql`.

## Reserverte, retirer­te numre

Aksjonær-/Top 20-funksjonen ble fjernet i PR #95. I forbindelse med denne funksjonen hadde følgende migreringer vært opprettet:

- SQLite: `0018_shareholder_snapshots.sql`
- Cloudflare D1: `0008_shareholder_snapshots.sql`

Filene er ikke lenger del av aktiv kodebase, men nummerene regnes som historisk brukt og skal ikke tas i bruk til noe annet.

**Neste nye migrering skal derfor minst være:**

- SQLite: `0019_...`
- Cloudflare D1: `0009_...`

## Regel for nye migreringer

1. Ikke endre innholdet i en migrering som kan være kjørt i en eksisterende database.
2. Ikke gjenbruk et retirert nummer.
3. Legg nye endringer i en ny, additiv og bakoverkompatibel migrering.
4. Husk at Worker-rollback ikke ruller tilbake D1-migreringer.
5. Bruk D1 Time Travel ved behov for databasegjenoppretting, ikke destruktiv omskriving av migreringshistorikken.

PR #95 fjernet selve aksjonærfunksjonen uten å kjøre destruktive `DROP TABLE`-operasjoner mot eksisterende produksjons-D1. Eventuelle gamle tabeller kan derfor finnes i en eldre database uten at de brukes av dagens applikasjon.

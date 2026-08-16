# Datamodell

Fase 2 etablerer et revisjonssporbart SQLite-datalag for Otello NAV Dashboard.

## Prinsipper

1. **Kilden først** – eksterne data registreres mot `sources` og normalt et konkret `source_document`.
2. **Eksakte finansielle verdier** – priser, beløp, prosenter og FX-rater lagres som desimaltekst og konverteres til `Decimal` i Python. Dette unngår binære flyttallsavrundinger.
3. **Historikk overskrives ikke** – beholdninger, aksjetall, estimater og NAV lagres med dato/tid slik at tidligere tilstand kan rekonstrueres.
4. **Provenance** – `provenance_records` kan peke fra et felt tilbake til dokument, side/avsnitt/API-lokator og ekstraksjonsmetode.
5. **Rådata og tolkning skilles** – `source_documents` representerer originalkilden, mens eksempelvis `company_news` klassifiserer dokumentet uten å endre originalen.

## Tabellgrupper

### Kilder

- `sources`
- `source_documents`
- `provenance_records`
- `source_health`
- `job_runs`

### Markedsdata

- `instruments`
- `market_prices`
- `fx_rates`

### Otello/Bemobi fundamentale data

- `bemobi_holdings`
- `otello_share_counts`
- `cash_anchors`
- `cash_movements`
- `other_net_assets_anchors`
- `buyback_programs`
- `buybacks`
- `corporate_actions`
- `company_news`

### Verdsettelse

- `nav_snapshots`

### Meglerestimater

- `broker_estimate_sets`
- `broker_estimate_values`
- `consensus_snapshots`

## Viktige invariants

- `outstanding_shares = total_shares - treasury_shares` håndheves av SQLite.
- Foreign keys er aktivert på hver forbindelse.
- Produksjonsdatabasen bruker WAL-modus for bedre samtidig lesing/skriving.
- Migreringer kjøres i filrekkefølge og registreres i `schema_migrations`.
- Samme migrering kjøres aldri to ganger mot samme database.

## Seed-data

Fase 2 oppretter referansekilder for Otello IR, Euronext, Bemobi IR, CVM, B3, ECB, brapi.dev, EODHD og manuell kontrollert registrering.

Instrumentene `OTEC` og `BMOB3` opprettes som basisinstrumenter.

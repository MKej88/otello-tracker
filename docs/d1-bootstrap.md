# Historisk SQLite -> D1 bootstrap

Phase 15.2 flytter **data**, ikke finansielle beregningsregler. Målet er å kunne ta en validert SQLite-referanse, lage en portabel bootstrap-pakke og bevise at en tom D1-instans ender med identiske historiske finans-/markedsdata.

## Hva som flyttes

Bootstrap-manifestet dekker:

- `sources` og `instruments` som identitetskontroll mot D1 migration `0002`;
- source documents og provenance;
- OTEC/BMOB3 market prices og market activity;
- FX;
- Bemobi-holdings;
- Otello share counts;
- cash anchors, movements, period calibrations og daily estimates;
- ONA reported anchors og daily estimates;
- buyback programs, weekly rows og daily transactions;
- corporate actions;
- CORE/FULL NAV snapshots;
- broker estimates og consensus snapshots.

Følgende er **ikke** historisk finansdata og resettes med vilje ved overgang til D1:

- `job_runs`;
- `source_health`;
- `runtime_state`.

Dette hindrer at gamle scheduler-statusser eller dirty-state fra SQLite påvirker den nye Cloudflare-runtime-en.

## Bootstrap-pakken

Eksporten består av to filer:

```text
bootstrap.sql
manifest.json
```

`bootstrap.sql` inneholder deterministiske `INSERT`-setninger i foreign-key-sikker rekkefølge. `sources` og `instruments` re-insertes ikke; de opprettes av D1 migration `0002_reference_data.sql` og må ha identisk ID/innhold med SQLite-referansen.

`manifest.json` inneholder for hver tabell:

- kolonneorden;
- radtall;
- logisk SHA-256 over alle rader i primary-key-rekkefølge.

I tillegg beregnes én global logisk SHA-256 samt finansielle kontrollpunkter:

- siste CORE/FULL NAV;
- market-data coverage per instrument/price type;
- FX coverage per valutapar;
- buyback-antall, aksjer og beløp;
- daily buyback-kontroll;
- siste cash-estimat;
- siste ONA-estimat;
- siste Otello share count;
- siste Bemobi-holding.

Hashen er **logisk**, ikke hash av SQLite-filen. WAL, page-layout, freelist og andre fysiske SQLite-detaljer påvirker derfor ikke kontrollsummen.

## Eksport fra validert SQLite

Fra repo-roten:

```bash
python cloudflare/tools/d1_bootstrap.py export \
  --database data/otello_nav.db \
  --sql data/d1-bootstrap/bootstrap.sql \
  --manifest data/d1-bootstrap/manifest.json
```

Eksporten nekter å fortsette dersom:

- `PRAGMA integrity_check` ikke er `ok`;
- foreign keys har brudd;
- forventede tabeller mangler;
- SQLite-referansen ikke står på migration `0016`.

Kilden åpnes read-only og leses i én SQLite snapshot-transaksjon, slik at en samtidig refresh ikke kan gi en halvveis eksport.

Bootstrap-filer er gitignored fordi de kan inneholde hele den historiske databasen.

## Lokal D1-import

Opprett schema/referansedata lokalt:

```bash
npx --yes wrangler@4 d1 migrations apply DB \
  --local \
  --config cloudflare/wrangler.schema-test.jsonc
```

Importer deretter data:

```bash
npx --yes wrangler@4 d1 execute DB \
  --local \
  --config cloudflare/wrangler.schema-test.jsonc \
  --file data/d1-bootstrap/bootstrap.sql
```

Eksporten er laget for en **fersk** D1-database etter migration `0001` + `0002`. Den bruker vanlige `INSERT`-setninger, slik at en utilsiktet re-import stopper på conflicts i stedet for å overskrive eksisterende produksjonsdata.

## Eksakt verifikasjon av lokal Wrangler D1

Verifieren kan få selve SQLite-filen eller Wrangler state-katalogen. Ved katalog finner den databasen ved å kontrollere schemaet:

```bash
python cloudflare/tools/d1_bootstrap.py verify \
  --database cloudflare/.wrangler/state/v3/d1 \
  --manifest data/d1-bootstrap/manifest.json
```

Pass krever samtidig:

1. samme radtall per manifest-tabell;
2. samme SHA-256 per tabell;
3. samme globale logiske SHA-256;
4. identiske finansielle nøkkeltall;
5. null `PRAGMA foreign_key_check`-brudd.

Det betyr at en endring helt ned på ett tekstfelt eller ett NAV-tall blir oppdaget.

## CI

CI bygger en deterministisk referansedatabase uten nettverk:

1. alle SQLite migrations kjøres;
2. repoets kuraterte Otello-historikk seeds;
3. representative OTEC/BMOB3/FX/cash/buyback/CORE/FULL-rader legges til;
4. bootstrap SQL + manifest eksporteres;
5. ekte lokal Wrangler D1 opprettes;
6. migration `0001` + `0002` anvendes;
7. bootstrap SQL importeres;
8. D1-databasen verifiseres mot manifestet med eksakte hashes og nøkkeltall.

Denne testen er separat fra `test_d1_schema_parity.py`: Phase 15.1 beviser **schema parity**, mens Phase 15.2 beviser **data parity**.

## Produksjonsimport

En remote D1-database opprettes ikke av denne fasen. Når den faktiske `otello-nav`-ressursen finnes, brukes den samme allerede validerte bootstrap-pakken:

```bash
npx wrangler d1 migrations apply DB --remote
npx wrangler d1 execute DB --remote --file data/d1-bootstrap/bootstrap.sql
```

Før remote import skal den konkrete produksjons-SQLite-referansen eksporteres og lokal parity være grønn. Etter remote import kjøres row-count/key-metric-verifikasjon gjennom Worker/D1-laget før D1 får bli autoritativ produksjonsdatabase.

## Viktig avgrensning

Bootstrap-koden endrer ikke:

- NAV-formler;
- cash-kurve/metodikk;
- ONA-metodikk;
- buyback-estimator eller Safe Harbour-logikk;
- kildeprioritet eller markedsprisregler.

Den serialiserer og kontrollerer eksisterende validerte rader nøyaktig som de er lagret.

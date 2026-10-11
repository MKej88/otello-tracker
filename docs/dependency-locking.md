# Låsing og integritet for avhengigheter

OtelloTracker har to ulike pakkeøkosystemer. Ikke forsøk å fjerne Scorecard-varsler
ved å fjerne hash-kontroller eller erstatte låste installasjoner med dynamiske.

## Python – hash-låste filer

Disse lockfilene ble generert på GitHub-hostet Linux (x86_64, Python 3.12)
med uv 0.12.3:

| Kilde | Generert lockfil | Bruk |
| --- | --- | --- |
| `backend/requirements.txt` | `backend/requirements.lock.txt` | Docker referanse-API |
| `backend/requirements-dev.txt` | `backend/requirements-dev.lock.txt` | Tester / lokal utvikling |
| `cloudflare/worker-tooling.in` | `cloudflare/worker-tooling.lock.txt` | CI og Worker-byggverktøy |

Produksjonskravene og direkte toppnivåversjoner er uendret. Underavhengighetene
er låst til nøyaktige versjoner, med SHA-256-hasher for tillatte distribusjoner.

Installer med `python -m pip install --require-hashes -r <fil>`; aldri installer
en ulåst requirements-fil i stedet uten eksplisitt beslutning.

Ved en ønsket avhengighetsoppdatering, generer lockfilene på nytt med **Python
3.12 og Linux x86_64** fra prosjektroten:

```sh
python -m pip install uv==0.12.3
uv pip compile backend/requirements.txt --python-version 3.12 --python-platform x86_64-manylinux_2_17 --generate-hashes --output-file backend/requirements.lock.txt
uv pip compile backend/requirements-dev.txt --python-version 3.12 --python-platform x86_64-manylinux_2_17 --generate-hashes --output-file backend/requirements-dev.lock.txt
uv pip compile cloudflare/worker-tooling.in --python-version 3.12 --python-platform x86_64-manylinux_2_17 --generate-hashes --output-file cloudflare/worker-tooling.lock.txt
python tools/check_dependency_integrity.py
```

Verifiser alle diffs i lockfilen før merge. Samme toppnivåversjon betyr ikke
nødvendigvis samme underavhengigheter ved ny lock-generering. Lockene er
Linux/Python 3.12-referanser, ikke en universell Windows/macOS-løsning.

## JavaScript / TypeScript

`frontend/package-lock.json` (lockfileVersion 3) har integritets-hasher
for alle eksternt oppløste npm-pakker. Bruk `npm ci`, ikke `npm install`,
i frontend-bygg. CI kjører også `tools/check_dependency_integrity.py`.

OpenSSF Scorecard kan rapportere `npmCommand not pinned by hash` på `npm ci`,
selv når `package-lock.json` inneholder SHA-baserte integrity-felter.
Dette er ikke grunn til å erstatte korrekt bruk av `npm ci`.

## Cloudflare Wrangler – låst npm-verktøykjede

Cloudflare CLI bruker `cloudflare/package.json` med direkte fastversjon
`wrangler@4.123.0` (i npm-manifestet: `"wrangler": "4.123.0"`).
`cloudflare/package-lock.json` låser underavhengigheter og deres SRI-hasher.

For Wrangler 4.123.0 blir den transitive `sharp`-avhengigheten fastsatt
til `0.35.5` med npm `overrides`, fordi `0.35.2` er berørt av
GHSA-rgj7-g3m4-5g8c og GHSA-wq5f-xc86-pv6w.
Den transitive `undici`-avhengigheten er tilsvarende låst til `7.29.1`,
som retter GHSA-w293-vg96-wgc3 og GHSA-rfgv-xxqx-mfg5.
Begge overstyringene må vurderes på nytt ved en senere Wrangler-oppgradering,
og Dependency Review må fortsatt være bestått.

Installer alltid med `npm ci --no-audit --no-fund` fra `cloudflare/`;
ikke `npm install --no-save wrangler@...`, som kan velge nye
transitive pakker. Produksjonsdeploy, testbygg og R2-snapshot-drill
skal bruke identisk lockfile.

For å oppdatere Wrangler: endre nøyaktig versjon i `cloudflare/package.json`,
kjør `npm install --package-lock-only --ignore-scripts --no-audit --no-fund`
i `cloudflare/` og kontroller endringen i PR. CI sjekker både npm-
og Python-hasher og kjører Cloudflare dry-run før merge.

## Verktøy for sikkerhetsskanning

`tools/pip-audit.in` og `tools/ruff.in` har eksakte versjoner. Tilsvarende
`tools/*.lock.txt` inneholder transitiv låsing og SHA-256-hasher, generert
med samme uv-kommando som over (med riktig input/output-sti).
Sikkerhetsanalysene installerer via `pip --require-hashes`.

OpenSSF Scorecard kan fortsatt rapportere utviklingsprosess-relaterte
kontroller; målet her er reproducerbar og verifiserbar installasjon,
ikke bare et lavere antall varsler.

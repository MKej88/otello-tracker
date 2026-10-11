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

**Begrensning:** Wrangler installeres ennå med eksplisitt direkteversjon
`wrangler@4.123.0`, men uten en transitive lockfil for det separate
Cloudflare-verktøyoppsettet. Dette krever egen vurdering og testing før
produksjonsworkflowen endres. Scorecard-varsler som gjelder dette kan
derfor fortsatt være åpne.

# Arkiverte GitHub Actions-arbeidsflyter

Disse YAML-filene er historiske referanser utenfor `.github/workflows` og kjøres ikke av GitHub Actions. Diagnoseverktøyene og regresjonstestene beholdes. Ved et eventuelt behov for gjeninnføring skal tilgang, triggere og produksjonsavgrensning vurderes på nytt i en pull request.

## 28. november 2026

- `bemobi-cvm-1477-diagnostic.yml`: Avgrenset lesediagnose for dokument 1477. Årsaken ble identifisert som utfylling etter PDF-sluttmarkøren; generell, verifisert normalisering ble innført i [#998](https://github.com/MKej88/otello-tracker/pull/998).
- `bemobi-cvm-7540-diagnostic.yml`: Avgrenset lesediagnose for dokument 7540. Årsaken og normaliseringskravene er dokumentert i [#993](https://github.com/MKej88/otello-tracker/pull/993). Den separate gjenopprettingsjobben beholdes.

Arkivering dokumenterer ikke at oversettelsene er ferdige. [#983](https://github.com/MKej88/otello-tracker/issues/983) følges opp separat; aktive oversettelses-, speilings- og gjenopprettingsjobber endres ikke.

## Konsoliderte CI-kontroller

- `python-worker-runtime-guard.yml`: Tidssonekontroll flyttet til obligatorisk Worker-API-jobb i [#1045](https://github.com/MKej88/otello-tracker/pull/1045).
- `python-static-analysis.yml`: Utvidet Ruff-kontroll flyttet til obligatorisk backend-jobb, med uendret separat låsefil, regelsett og filunntak. Eksisterende Ruff-formatkontroll og mypy beholdes.
- `python-dependency-audit.yml`: PR/main-kontroll dekkes av obligatorisk backend-CI. Ukentlig pip-audit flyttes uendret til Actions-sikkerhetsanalysen mandag 05:41 UTC (tidligere 05:17), med eget skrivebeskyttet jobbmiljø og manuell kjøring.

## Manuelle produksjonskontroller

- `verify-production-sources.yml`: Flyttet til `manual-cloudflare-full-refresh.yml` som valget `kildekontroll`. Begge eksisterende kontrollvarianter beholdes med uendrede jobbsteg, men kan bare startes manuelt på main og bruker samme concurrency-gruppe. Den tidligere push-triggeren på den gamle YAML-filen fjernes for å unngå produksjonsskriving ved ren arbeidsflytvedlikehold. Dato-standardene forblir Oslo og UTC, respektivt.
- `verify-exr-production.yml`: Flyttet uendret kontrolljobb til `cloudflare-workflow-diagnostics.yml` som manuelt valg `brl-nok` eller `begge`. Kun main, skrivebeskyttet Cloudflare-token, ingen endring i nattdiagnostikk/varsler. Tidligere push-trigger på den gamle YAML-filen erstattes av eksplisitt manuell produksjonskontroll.

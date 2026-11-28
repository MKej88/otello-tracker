# Arbeidsflyter i GitHub Actions

Arbeidsflytene grupperes etter funksjon. Visningsnavnene er norske og nummererte, men filnavn, jobb-ID-er, obligatoriske kontrollnavn, tidsplaner, tilgangsregler og gjenbrukbare kall beholdes.


| Nummer | Arbeidsflyt | Fil |
| --- | --- | --- |
| 01 | Kontinuerlig integrasjon (CI) | ci.yml |
| 02 | Produksjonsutrulling | deploy-cloudflare.yml |
| 03 | Validering av produksjonskonfigurasjon | production-config-ci.yml |
| 10 | Produksjonsdiagnostikk | cloudflare-workflow-diagnostics.yml |
| 11 | Manuell fulloppdatering | manual-cloudflare-full-refresh.yml |
| 12 | Ytelsesovervåkning | production-performance.yml |
| 13 | Kontroll etter Oslo Børs | verify-after-oslo-close.yml |
| 14 | Manuell publisering av diagnosestatus | publish-cloudflare-diagnostic-status.yml |
| 20 | Bemobi – innhenting av CVM-dokumenter | bemobi-cvm-live-r2.yml |
| 21 | Bemobi – speiling av oversettelseskø | bemobi-translation-r2-mirror.yml |
| 22 | Bemobi – 24 måneders oversettelseshistorikk | bemobi-translation-history.yml |
| 23 | Bemobi – lesediagnostikk | bemobi-diagnostics.yml |
| 24 | Bemobi – kontroll av investorinformasjon og rentebasert utbytte | bemobi-ir-jcp-readonly.yml |
| 25 | Bemobi – speiling av verifiserte Q3-dokumenter | bemobi-verified-r2-mirror.yml |
| 26 | Bemobi – gjenoppretting av CVM-dokument 7540 | bemobi-cvm-7540-recovery.yml |
| 30 | Kontroll av sikkerhetskopier | r2-snapshot-drill.yml |
| 40 | Sikkerhetsanalyse av kode (CodeQL) | codeql.yml |
| 41 | Sikkerhetsanalyse av arbeidsflyter og Python-avhengigheter | actions-security-analysis.yml |
| 42 | Kontroll av nye avhengigheter | dependency-review.yml |
| 43 | Sikkerhetsvurdering (OpenSSF Scorecard) | scorecard.yml |
| 50 | Validering av tilbakekjøpsmodell | buyback-model-validation.yml |

## Produksjonsskriving ved vedlikehold av arbeidsflyter

Endring av de fem Bemobi-arbeidsflytenes egne YAML-filer utløser ikke lenger speiling, køinnlegging eller historisk reaktivering. Relevante kodeendringer, planlagte kjøringer og manuelle valg er beholdt. Endringer i produksjonsjobbenes YAML må verifiseres manuelt eller ved neste planlagte kjøring. For Q3-speiling og 7540-gjenoppretting uten egen tidsplan benyttes manuell kjøring ved behov. PR-validering beholdes der den eksisterte. Referer til YAML-filnavn eller arbeidsflyt-ID i automatiseringer. Historiske kjøringer og arkiverte arbeidsflyter beholdes. Se [arkiv](archive/github-actions/README.md).

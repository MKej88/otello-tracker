# Teknisk gjeld – gjennomgang 28.11.2026

## Avgrensning

Første kartlegging av repoets filstruktur, alle 32 GitHub-workflows, sentrale cachemoduler og aktiv frontend. Dette er ikke en fullstendig statisk analyse av alle importreferanser eller en ny revisjon av finansielle formler. Ingen produksjonsdata, modellverdier, migreringshistorikk eller aktive oversettelsesjobber slettes eller endres.

## Workflow-inventar

| Gruppe | Filer under .github/workflows | Beslutning |
| --- | --- | --- |
| CI og sikkerhet (9) | ci, actions-security-analysis, codeql, dependency-review, production-config-ci, python-dependency-audit, python-static-analysis, python-worker-runtime-guard, scorecard | Behold. Kontroller eventuelle overlapp mot obligatoriske mergekontroller før endringer. |
| Produksjonsdrift (9) | deploy-cloudflare, cloudflare-workflow-diagnostics, manual-cloudflare-full-refresh, production-performance, publish-cloudflare-diagnostic-status, r2-snapshot-drill, verify-after-oslo-close, verify-exr-production, verify-production-sources | Behold. Skille mellom automatikk, manuell beredskap og målinger; ikke fjern nattdiagnose eller gjenoppretting. |
| Løpende Bemobi-innhenting (3) | bemobi-cvm-live-r2, bemobi-translation-history, bemobi-translation-r2-mirror | Behold mens oversettelseskøen behandles. De har egne cron-planer. |
| Hendelsesspesifikke Bemobi-verktøy (10) | bemobi-cvm-1477-diagnostic, bemobi-cvm-7540-diagnostic, bemobi-cvm-7540-recovery, bemobi-cvm-rad-probe, bemobi-five-document-diagnostic, bemobi-five-document-recovery, bemobi-ir-jcp-readonly, bemobi-translation-archive-audit, bemobi-translation-recovery-20261127, bemobi-verified-r2-mirror | Gjennomgå etter at #983 er avsluttet; behold sporbarhet og lesediagnostikk. Engangsreaktivering av fem dokumenter er fullført, og automatisk skriving på push fjernes i denne endringen. |
| Modellkontroll (1) | buyback-model-validation | Behold manuell uavhengig kontroll. |

Filnavnene i tabellen har endelsen .yml. Elleve workflows har schedule-trigger; dette er ikke det samme som antall cron-uttrykk. Cloudflare Worker-cron kommer i tillegg.

### Engangsreaktivering 28.11

[Produksjonskjøring 46139684541](https://github.com/MKej88/otello-tracker/actions/runs/46139684541) reaktiverte fem historiske dokumenter. [Diagnose 46146073913](https://github.com/MKej88/otello-tracker/actions/runs/46146073913) bekrefter at dokument 7538 gjenbrukte tidligere verifiserte deler (12/59), uten nye feil i siste kjøring. Engangsskrivingen skal derfor ikke kunne trigges på senere kodeendringer. Manuell recovery på main og PR-validering beholdes, inklusive uendrede avgrensninger og sammenlign-og-oppdater. Normal 30-minuttersbehandling påvirkes ikke.

CI kaller fortsatt 7540-recovery etter deploy, med egen avgrensning som hopper over skriving når den relevante normaliseringen ikke er endret. Vurder å flytte denne hendelsesspesifikke koblingen ut av ordinær CI når dokumentstatus og behov for manuell recovery er verifisert. Ikke konkluder med at dokumentet er ferdig oversatt ut fra en grønn deployjobb.

## Prioritert restarbeid

| Prioritet | Funn | Neste kontroll / akseptanse |
| --- | --- | --- |
| 1 | Eldre frontendkomponenter App.tsx, HistoryPage.tsx, DeferredDiagnostics.tsx og EconomicNavPanel.tsx | Kartlegg direkte og indirekte import, dynamiske importer, stilark og testreferanser. Aktiv inngang er main.tsx -> InvestorApp.tsx. Ikke slett basert på filnavn eller fravær i et ufullstendig søk. |
| 2 | Hendelsesspesifikke recovery-workflows og diagnoseverktøy | Når #983 er ferdig: verifiser eksakte dokumentstatus, avhengigheter og historiske kontrollkrav. Fjern automatiske skrivetilganger som ikke lenger trengs; behold reproduserbare verktøy og evidens. |
| 3 | Gamle reservekilder, særlig ECB og overlappende CVM/IR | Lag kilde-/fallbackmatrise per aktiv beregning. Skill inaktiv innhenting fra bevart provenance og faktisk reserve. Ingen fjerning av historiske valutakurser eller originaldokumenter. |
| 4 | Dobbeltimplementering i backend/ og cloudflare/ | Referansebackend er tilsiktet uavhengig regresjonsmotor. Kartlegg faktisk regelverks- og formelavvik med paritetstester, ikke slå sammen bare fordi kodemønstre ligner. |
| 5 | Flere cache- og snapshotlag | Dokumenter eier, nøkkel, maksimal alder, fallback og ugyldiggjøring per endepunkt. Behold separat historikk og intradag. Mål cold/non-HIT før endring. |
| 6 | Historiske revisjonsnotater og utdaterte beskrivelser | Oppdater aktiv arkitekturdokumentasjon. Behold daterte revisjoner som evidens: eksterne-api-audit.md og eksterne_api_audit.md har forskjellig omfang og er ikke identiske. |
| 7 | Ytelsesmålinger | Europeisk runner krever faktisk provisionert infrastruktur. Se production-performance-followup.md. Ikke bland europeiske og amerikanske trendserier. |

## Sikringsregler

- Ingen endring i aktiv oversettelsesprosess før #983 er kontrollert.
- Følg opp automatisk nattdiagnose i #977 og JCP-avstemming i #928 på de avtalte datoene.
- Før fjerning av kode: kontroller referanser, obligatorisk CI, lokal/regresjonsparitet og produksjonsakseptanse.
- Før fjerning av en datakilde: dokumenter bruk i historiske beregninger og faktisk reservefunksjon, og verifiser ny kilde.
- Behold alle anvendte migreringsnumre og historiske originaler.

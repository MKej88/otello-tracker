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
| 1 | Eldre frontendkomponenter App.tsx, HistoryPage.tsx, DeferredDiagnostics.tsx og EconomicNavPanel.tsx | Fase 2: fjernet fire komponenter uten aktive importreferanser etter gjennomgang av alle TypeScript-filer under frontend/src. To kontrakttester peker nå på aktive visninger. Fase 6: tre eldre paneler (NavWaterfallPanel, ReportStatusPanel og RuntimeStatusPanel) og fem ubrukte stilark fjernes, totalt ca. 50,1 kB kildekode. Mobiltest for historikk peker på aktiv investor-v2.css og EstimatedHistoryPage. Tema- og importkontrakter beholdes for aktive filer. Fase 8: MarketQuotePanel og market-quote-panel.css fjernes etter at uendrede datatyper og aktiv intervallberegning er flyttet til marketQuoteModel.ts. Markeds-, cache- og temakontrakter kontrollerer nå aktive visninger. Ingen nye markedsfunksjoner eller endret layout. ConsensusHistoryPanel og tilhørende stilkandidat vurderes separat; ikke fjern aktiv funksjonalitet. Ingen endring i globale stiler eller aktive API-ruter. |
| 2 | Hendelsesspesifikke recovery-workflows og diagnoseverktøy | Når #983 er ferdig: verifiser eksakte dokumentstatus, avhengigheter og historiske kontrollkrav. Fjern automatiske skrivetilganger som ikke lenger trengs; behold reproduserbare verktøy og evidens. |
| 3 | Gamle reservekilder, særlig ECB og overlappende CVM/IR | Fase 3: se [kildehierarki og reserver](kildehierarki-og-reserver.md). ECB merkes som historisk reserve i diagnosen. Behold eksisterende kildevalg og historikk; konkret reduksjon i nettverkskall krever måling og regresjonstest. |
| 4 | Dobbeltimplementering i backend/ og cloudflare/ | Fase 4: [finansiell modellparitet](finansiell-modellparitet.md), utvidede tester for opsjoner, kontantbro, NAV-attribusjon og betalingsomklassifisering. Behold separate beregningsmotorer. Full paritet for alle datatilganger gjenstår. |
| 5 | Flere cache- og snapshotlag | Fase 5: [cachearkitektur](cachearkitektur.md). Samordnet struktur- og aldersvalidering for dashboard-snapshot. Behold separat historikk og intradag. Måling av TTL og nettleserens revalidering gjenstår. |
| 6 | Historiske revisjonsnotater og utdaterte beskrivelser | Oppdater aktiv arkitekturdokumentasjon. Behold daterte revisjoner som evidens: eksterne-api-audit.md og eksterne_api_audit.md har forskjellig omfang og er ikke identiske. |
| 7 | Ytelsesmålinger | Europeisk runner krever faktisk provisionert infrastruktur. Se production-performance-followup.md. Ikke bland europeiske og amerikanske trendserier. |

## Sikringsregler

- Ingen endring i aktiv oversettelsesprosess før #983 er kontrollert.
- Følg opp automatisk nattdiagnose i #977 og JCP-avstemming i #928 på de avtalte datoene.
- Før fjerning av kode: kontroller referanser, obligatorisk CI, lokal/regresjonsparitet og produksjonsakseptanse.
- Før fjerning av en datakilde: dokumenter bruk i historiske beregninger og faktisk reservefunksjon, og verifiser ny kilde.
- Behold alle anvendte migreringsnumre og historiske originaler.

## Fase 9 – Mobilkontroll

CI 46150999219, Worker-jobb 140997403035, hadde grønn status, men loggen viste timeout i browser-smoke: den ventet på en eldre NAV-selektor selv om dagens V3-forside viste NAV. Kommandoens pipeline gjennom tee kunne maskere Node-feil i standard bash. Rettelsen oppdaterer selektorer og kortetiketter til dagens visning, aktiverer pipefail, krever en konkret sidemarkør og korrekt viewport før mobilmåling, og logger hver av 36 kombinasjoner. Dette er en styrking av kontrollen, ikke en verifisert mobil-layoutrettelse. Ny reell browser-smoke må gjennomføres før mobilstatus kan bekreftes. Ingen visuell CSS eller finansmodell endres.

Oppfølging av PR #1024: Worker-jobb 140999233507 viste at lokal testdatabase svarte med utilstrekkelig kildebelagt historikk for valgt 1-årsperiode. Browser-smoke henter derfor nøyaktig samme API-spørring som historikkvisningen og krever graf ved `ready=true` (med statistikk), eller eksplisitt tomtilstand ved `ready=false`. Faktisk innlastingsfeil godtas ikke. Tomtilstand er ikke en bestått grafkontroll; en separat datarik fixture for historikkgrafen er fortsatt ønskelig. Pipefail beholdes.

Worker-jobb 141000007722 bekreftet historikkens tomtilstand, men stoppet ved tilbakekjøp (`NO_ACTIVE_PROGRAM` i lokal fixture). Browser-smoke avklarer nå aktivt datagrunnlag mot de eksakte API-kallene også for tilbakekjøp, Bemobi, konsensus, FX og Brasil. Tilbakekjøp godtar kun eksplisitt NO_ACTIVE_PROGRAM som tomtilstand. HTTP-feil og manglende entydig status feiler. Logg skiller tomtilstand fra full datavisning; rikere fixture er nødvendig for å teste samtlige datakort. Ingen produksjonsberegning eller CSS endres.

Worker-jobb 141000956234: 12/12 ved 390 px og fem første ved 320 px bestod (17/36 før stopp). Cash-siden hadde dokumentbredde 342 px ved viewport 320 px. Smal Cash-layout (<380 px) får krympbare gridspor, brytbare tekster og stablede overskrifter, uten skjuling av innhold. Browser-smoke samler nå layoutavvik fra alle kombinasjoner før ikke-null exit og logger kandidater til overflyt. Årsakselementet er ikke isolert i tidligere logg; CSS-rettelsen må verifiseres i ny CI. Tomtilstandskontroller og pipefail beholdes.

# Rettelse av manglende nattoppdatering, 29. september 2026

Produksjonsstatusen kl. 07.14 norsk sommertid viste siste fullkjøring 27. september
kl. 05.35–05.38, med datadato 26. september. 30-minuttersjobben kjørte fortsatt.
Diagnoseloggen 28. september viste ingen Workflow-instans for den dagen.
Dette avgrenser feilen til oppstarten, men beviser ikke en bestemt Cloudflare-feil
eller en bestemt kodeendring.

## Endring

- Beholder 03.35 UTC hver dag (05.35 sommertid, 04.35 vintertid).
- Starter den eksisterende FullRefreshWorkflow fra Worker cron og tømmer den
  separate native Workflow-tidsplanen, slik at det bare er én primær utløser.
- Etter hver 30-minuttersjobb kontrolleres om dagens nattkjøring mangler.
- Eksisterende SUCCESS/RUNNING for riktig datadato respekteres ved overgang.
- Fast instans-ID `nightly-YYYY-MM-DD` hindrer nye instanser ved dupliserte forsøk.
- Feilet/terminert instans restartes ikke automatisk; den krever undersøkelse.
- En manglende dagskjøring markeres forsinket etter 55 minutters frist.
- Brukergrensesnittet viser forsinkelse, faktisk starttid og tydelig merket datadato.

Endringen må publiseres før den kan reparere produksjonen. Etter publisering skal
neste 30-minutterskjøring kunne starte nattjobben for foregående kalenderdato.
Kontroller deretter at API-et viser ny start/slutt og at Workflow er fullført.
Fullkjøringen beholder eksisterende innhenting, skrivelås og e-postrapportering.
Automatisk recovery gjelder dagens forventede kjøring, ikke separat omkjøring av
hver tidligere manglende natt.

## Kontrollert lokalt

- Tester for recovery, tidssoner/helg, duplikater og API-feil.
- Tester for cron-dispatch, produksjonskonfigurasjon, runtime-status og diagnostikk.
- Frontend-tester, TypeScript og production build.
- Ruff-kontroll av Worker-koden og `git diff --check`.

## Kilder

- https://otellotracker.com/api/dashboard/runtime-status
- https://github.com/MKej88/otello-tracker/actions/runs/36413699885
- https://developers.cloudflare.com/workflows/python/bindings/
- https://developers.cloudflare.com/workflows/build/trigger-workflows/

## Dobbeltkjøring 17. oktober 2026

Diagnose 39014079779 viste både den native instansen `35 3 * * *-1792208100000`
og Worker-instansen `nightly-2026-10-16`. Den siste ventet på skrivelåsen og
kjørte deretter samme datadato på nytt. Begge fullførte og sendte statusmail.

- Native `workflow_schedule:`-oppstarter avsluttes nå som SKIPPED før skrivelås,
  innhenting eller e-post. Worker cron og reservekontrollen beholdes.
- Under skrivelåsen kontrolleres SUCCESS for samme datadato på nytt. En automatisk
  duplikat avsluttes uten ny jobb eller e-post, og låsen slippes i finally.
- Manuelle omkjøringer og recovery etter PARTIAL/FAILED beholdes.
- Deploy tømmer fortsatt native schedules via PUT, men leser nå også Workflow
  tilbake og feiler dersom en tidsplan fortsatt finnes. Ingen historikk slettes.

Regresjonstester kjører de faktiske tidlige returene i Workflow-orkestreringen,
kontrollerer at låsen slippes og at ingen ny innhenting/e-post starter, og sjekker
SUCCESS/PARTIAL/FAILED, datodifferanser, ugyldig metadata og manuell omkjøring.

Kilde: https://github.com/MKej88/otello-tracker/actions/runs/39014079779

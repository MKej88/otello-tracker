# Automatisk kontroll av nattkjøring og kildeferskhet

Den eksisterende read-only GitHub-diagnosen kjører daglig kl. 04.30 UTC, etter
nattoppdateringen kl. 03.35 UTC. GitHub kan forsinke planlagte jobber. Endringer i
selve diagnoseoppsettet eller kontrollmodulen utløser også en kontroll på main.
Manuell kjøring er fortsatt tilgjengelig og viser avvik uten å feile proben.

## Kontroller

- Forventet nattjobb skal ha SUCCESS etter 55 minutters frist. Datadato er dagen
  før den forventede UTC-oppstarten. Før fristen vurderes foregående natt.
- Flere SUCCESS-jobber for samme forventede datadato markeres som avvik. SKIPPED
  Workflow-instanser telles ikke. FAILED/PARTIAL etterfulgt av én SUCCESS er en
  recovery og regnes ikke som duplisert suksess. En bevisst manuell omkjøring som
  gir to SUCCESS vises også som avvik og må vurderes.
- Alle sju kildegrupper må ha OK og en gyldig kontroll siste 36 timer.
- OTEC og BMOB3 må ha sluttkurs fra siste forventede børsdag. Eksisterende Oslo-
  og B3-kalendere brukes. Life360 LIF bruker eksisterende toleranse på sju
  kalenderdager, siden prosjektet ikke har en egen amerikansk børskalender.
- Bemobi IR og CVM må være kontrollert for forventet datadato og lagret siste
  36 timer. CVM-arkivets Last-Modified-dato kontrolleres separat med prosjektets
  eksisterende tredagersgrense. Manglende datadato gir avvik.
- Nyhetskildene behøver ikke publisere en ny melding hver dag: ferskhet betyr
  at feeden/arkivet faktisk er hentet, ikke at publiseringsdatoen er ny.
- Eksisterende valutakontroll, 30-minuttersjobb og NAV-diagnostikk beholdes.

Rapporten viser kontroller med faktisk/forventet verdi og fullkjøringer siste
åtte døgn med norsk tid. Rå metadata, kildefeil og hemmeligheter tas ikke med i
den nye rapporten. SQL-spørringene er kun SELECT og krever ingen nye rettigheter.

## Varsling og verifikasjon

Automatiske diagnoser med avvik feiler i GitHub Actions og gir feilannotasjon.
GitHub sender e-post etter brukerens eksisterende varslingsinnstillinger; det er
ikke lagt til en separat e-postutsending. Den vanlige statusmailen fra nattjobben
beholdes. Eksisterende publisering av diagnosestatus beholdes.

Kontrollene er testet med manglende/doble jobber, recovery, datoovergang, frist,
helg og ulik norsk/brasiliansk børsfridag, gamle og fremtidsdaterte observasjoner,
CVM-filalder og en nyhetsfeed uten nye meldinger. Workflowens faktiske Python-
blokker testes med ni spørringer og både OK- og avviksresultat.

Kilder:
- .github/workflows/cloudflare-workflow-diagnostics.yml
- cloudflare/src/production_monitor.py
- cloudflare/src/oslo_calendar.py og cloudflare/src/b3_calendar.py
- cloudflare/src/life360_market_data.py og cloudflare/src/cvm_full_refresh.py

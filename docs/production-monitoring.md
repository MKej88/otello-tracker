# Automatisk kontroll av nattkjøring og kildeferskhet

Den eksisterende read-only GitHub-diagnosen kjører daglig kl. 04.30 UTC, etter
nattoppdateringen kl. 03.35 UTC. GitHub kan forsinke planlagte jobber. Ved pull request og push/merge til main
kjøres kun offline regresjonstester av diagnosepolitikken. Den seneste
nattkjøringen kan være fra før en ny produksjonsversjon er utrullet og skal
ikke føre til rød GitHub Actions-kjøring for selve kodeendringen.
Live produksjonsdiagnose leser Cloudflare/D1 bare på den daglige tidsplanen,
eller ved manuell kjøring. Manuell kjøring viser avvik uten å feile proben.

## Kontroller

- Forventet nattjobb skal ha SUCCESS etter 55 minutters frist. Datadato er dagen
  før den forventede UTC-oppstarten. Før fristen vurderes foregående natt.
- Flere SUCCESS-jobber for samme forventede datadato markeres som avvik. SKIPPED
  Workflow-instanser telles ikke. FAILED/PARTIAL etterfulgt av én SUCCESS er en
  recovery og regnes ikke som duplisert suksess. En bevisst manuell omkjøring som
  gir to SUCCESS vises også som avvik og må vurderes.
- Alle sju kildegrupper må ha OK og en gyldig kontroll siste 36 timer.
- OTEC må ha offisiell CLOSE eller en Euronext-LAST eksplisitt merket som
  EOD_LAST_TRADE/WORKFLOW_R2_RECOVERY fra siste forventede børsdag. Vilkårlige
  intradagshandler godtas ikke. OTEC-kontrollen heter «kurs ved dagsavslutning»;
  siste rapporterte handel fremstilles ikke som offisiell sluttkurs. BMOB3 må ha
  CLOSE fra siste forventede børsdag. Eksisterende Oslo-
  og B3-kalendere brukes. Life360 LIF bruker eksisterende toleranse på sju
  kalenderdager, siden prosjektet ikke har en egen amerikansk børskalender.
- Bemobi IR og CVM må være kontrollert for forventet datadato og lagret siste
  36 timer. CVM IPE oppdateres ukentlig; Last-Modified kontrolleres derfor
  med inntil ti kalenderdager (syv dager + tre dagers toleranse).
  Manglende datadato eller eldre arkiv gir avvik.
- Nyhetskildene behøver ikke publisere en ny melding hver dag: ferskhet betyr
  at feeden/arkivet faktisk er hentet, ikke at publiseringsdatoen er ny.
- Eksisterende valutakontroll, 30-minuttersjobb og NAV-diagnostikk beholdes.

Rapporten viser kontroller med faktisk/forventet verdi og fullkjøringer siste
åtte døgn med norsk tid. Rå metadata, kildefeil og hemmeligheter tas ikke med i
den nye rapporten. SQL-spørringene er kun SELECT og krever ingen nye rettigheter.

## Varsling og verifikasjon

Automatiske diagnoser med avvik feiler i GitHub Actions og gir feilannotasjon.
I tillegg lytter `.github/workflows/production-incident-notify.yml` på
ferdigstilte, planlagte diagnoser fra `main`. Ved en feilet nattdiagnose eller
30-minuttersvakt oppretter eller gjenåpner den én deduplisert GitHub-sak per
kontrolltype, med kun lenke til Actions-loggen og uten følsomme produksjonsdata.
Saken tildeles repository-eier og lukkes ved neste vellykkede kontroll **av
samme type**. E-post/push fra slike saker krever at brukeren har slått på
GitHub-varsler for tildelte saker. Den sender ikke e-post direkte.

CORE-NAV `DEGRADED` skilles i diagnostikken mellom normal estimering mellom
rapporter (MODELLINFO) og reelle kvalitetsadvarsler (ADVARSEL). Delvis
kontantprognose eller mulig foreldet aksjeantall skal ikke alene utløse feil.
Høy rest i kontantavstemmingen eller uforklart `DEGRADED` skal gi advarsel;
manglende eller ugyldig status er fortsatt kritisk avvik.

GitHub sender e-post etter brukerens eksisterende varslingsinnstillinger; det er
ikke lagt til en separat e-postutsending. Den vanlige statusmailen fra nattjobben
beholdes. Eksisterende publisering av diagnosestatus beholdes.

Kontrollene er testet med manglende/doble jobber, recovery, datoovergang, frist,
helg og ulik norsk/brasiliansk børsfridag, gamle og fremtidsdaterte observasjoner,
CVM-filalder og en nyhetsfeed uten nye meldinger. Workflowens faktiske Python-
blokker testes med tolv spørringer og både OK- og avviksresultat.

Kilder:
- .github/workflows/cloudflare-workflow-diagnostics.yml
- cloudflare/src/production_monitor.py
- cloudflare/src/oslo_calendar.py og cloudflare/src/b3_calendar.py
- cloudflare/src/life360_market_data.py og cloudflare/src/cvm_full_refresh.py

## Innføring 17. oktober: historikk og første måling

Den første diagnosen i PR 785/786 krevde nye ferskhetsfelter fra nattjobben som
allerede hadde kjørt før feltene ble innført i PR 783. Manglende felt vises derfor
som AVVENTER frem til første forventede natt med datadato 17. oktober. Fristen er
18. oktober kl. 06.30 norsk tid. Fra denne fristen gir manglende felt AVVIK.
Eksisterende ugyldige/gamle felt og kildefeil får ingen slik utsettelse.

Dobbeltkjøringen for datadato 16. oktober er en avsluttet hendelse: rettelsen i
PR 784 er publisert, og den gamle tidsplanen er bekreftet fjernet. Akkurat de to
dokumenterte kjøringene med start/slutt 03.36.00.356–03.38.59.833 UTC og
03.43.04.680–03.46.36.876 UTC markeres HISTORISK. Historikken beholdes. Et nytt
forsøk, endrede tidspunkter eller en annen datadato omfattes ikke av kvitteringen.

Diagnosegrunnlag: https://github.com/MKej88/otello-tracker/actions/runs/39014079779
Rettelse: https://github.com/MKej88/otello-tracker/pull/784

## NAV og mellomlagrede data

Diagnosen avstemmer også NAV-aritmetikk, grunnlagsrader og de viste tallene mot
D1, og kontrollerer cache-versjon, alder og nettsidens faktiske bootstrap-svar.
Se [nav-cache-audit.md](nav-cache-audit.md) for modeller, toleranser og håndtering
av oppdateringer som pågår.

# Målrettet frontend-audit, 7. september 2026

## Metode og critical path

Gjennomgangen følger både førstegangsbesøk og navigasjon mellom visninger ved å
spore ruting, dynamiske importer, request-start, delte promises, React-hooks og
rendering i kildekoden. Produksjonsbygget ble brukt til å måle modulstørrelser.
Miljøet har ikke Chrome/Chromium, så millisekunder er estimert fra den påviste
waterfallen i stedet for å presenteres som en nettlesermåling.

Førstesiden har denne stien:

1. `index.html` starter `/api/dashboard/bootstrap` før JavaScript-pakken.
2. React monterer den ikke-kodesplittede oversikten.
3. Fem av seks synlige ressurser gjenbruker bootstrap; rabatt-historikken starter
   separat. Polling-hookene kjører uavhengig uten sekvensielle `await`.
4. Hver ressurs oppdaterer avgrenset state når den er klar. Listene er små, og
   gjennomgangen fant ingen tung synkron databehandling eller materiell
   DOM/layout/paint-kostnad.

Ved navigasjon kaller brukerhandlingen `preload(view)` før hash-ruten endres.
Denne funksjonen starter både den kode-splittede modulen og kjente datarequests.
`navigationDataPreload` deler pågående promises og en kort cache, slik at den
monterte visningen ikke behøver å sende samme request på nytt.

## Kandidater

| Kandidat | Startpunkt → sluttpunkt | Måling/estimat | Avhengighet og prioritering |
| --- | --- | --- | --- |
| Sen start av live NAV og tilbakekjøpsgrunnlag | Klikk/fokus/direkte NAV-rute → nedlasting og kjøring av `NavPageV2` → to API-kall → korrekte nøkkeltall | Begge kall ventet på den dynamiske NAV-modulen. Bygget måler modulen til 14,97 kB / 4,57 kB gzip. Den påførte ventetiden er derfor én modulnettverksrunde pluss overføring/parse før API-latensen kan begynne; anslått omtrent 50–200 ms på vanlig mobilnett, mer ved høy latenstid. | API-ene bruker ikke modulresultatet eller hverandres resultat. Høy effekt og sikkerhet, svært lav kode- og datarisiko. **Valgt.** |
| Rabatt-historikk på Oversikt utenfor bootstrap | React effect → historikk-API → median synlig | Ett separat kall og opptil 72 punkter. | Kan spare en nettverksrunde, men øker bootstrap-størrelse og kobler data med ulik levetid. Middels effekt, høyere cache-/korrekthetsrisiko. Ikke valgt. |
| NAV-periodepakke | Navigasjon → materialisert periodepakke → graf | Allerede ett parallelt kall for alle perioder, med delt promise og direkte fallback. | Ingen falsk avhengighet eller duplikat funnet. Ikke endret. |
| React-rendering og klientberegning | API-resultat → state → render → paint | Små datasett og uavhengige state-oppdateringer; ingen blokkerende løkker på navigasjonsstien. | Ingen dokumentert materiell flaskehals. Ikke endret. |
| Backend-latency | Request-start → respons | Kan fremdeles dominere total tid, særlig ved Worker-oppstart, men frontend-waterfallen la modulventing foran denne tiden. | Backendarbeid er ikke nødvendig for å fjerne den dokumenterte frontendventingen. Ikke endret. |

Vurdert som effekt × sikkerhet ÷ risiko/kompleksitet gir den sene request-starten
klart best forhold. Det er derfor den eneste produksjonsendringen.

## Endring og korrekthet

`preload("NAV")` starter nå live NAV og tilbakekjøpsgrunnlaget samtidig med den
dynamiske modulen og periodepakken. NAV-visningens polling-hooks er satt til å
gjenbruke disse promise-ene ved første lasting. Dermed går stien fra

`brukerhandling → modul ferdig → API-start → respons → render`

til

`brukerhandling → modul og API parallelt → respons → render`.

Requests er reelt uavhengige: URL-ene har ingen parametere som produseres av
modulen, periodepakken eller hverandre. Den eksisterende request-samleren beholder
samme HTTP-feilhåndtering og 30-sekunders cache. Senere polling bruker fortsatt de
ordinære endepunktene, så ferskhet og revalidering er uendret.

## Før og etter

Samme statiske critical-path-analyse viser:

- **Før:** live NAV og tilbakekjøpsgrunnlag startet først etter at NAV-chunken var
  lastet, tolket og montert.
- **Etter:** begge starter i samme synkrone `preload`-kall som chunkinnlastingen.
- **Duplikater:** første komponentlasting gjenbruker de pågående requestene; det er
  fortsatt ett kall per URL, ikke et preload-kall pluss et komponentkall.
- **Bygg:** NAV-chunken er 14,97 kB / 4,57 kB gzip. Endringen legger ikke til en
  avhengighet eller en ny request, men flytter de eksisterende kallene tidligere.

En kontrakttest låser både tidlig start før ruteendringen og gjenbruk i
polling-hookene. Faktisk LCP/INP bør som oppfølging måles i en nettleser mot
produksjons-API-et; det var ikke praktisk mulig i dette miljøet.

## Oppfølgingsfunn: Cash-visningen

En ny gjennomgang av hele navigasjonsstien avdekket én materiell feil som ikke
var dekket av NAV-forbedringen:

| Kandidat | Startpunkt → sluttpunkt | Måling/estimat | Avhengighet og prioritering |
| --- | --- | --- | --- |
| Dupliserte Cash-kall og sent økonomikall | Klikk/fokus → preload → modulinnlasting → komponent-effect → nyttige cash-tall | Statisk request-opptelling viste 9 kall: 4 preload-kall, 4 duplikater etter montering og 1 ubrukt kall. Økonomidata startet først etter Cash-chunken. Etter endringen er dette 4 delte kall. Det fjerner 5 kall (56 %) på første navigasjon og flytter økonomikallet én modulnettverksrunde tidligere. | Ingen av de fire responsene avhenger av en annen respons eller av modulkoden; komponenten brukte allerede `Promise.allSettled`. Høy effekt og sikkerhet, lav risiko. **Valgt.** |
| Samlet backend-endepunkt for Cash | Navigasjon → ett aggregert svar → alle kort | Kunne redusert fire kall til ett, men ville krevd ny backend-kontrakt og endret caching-/feildomener. | Mulig høy effekt, men betydelig større korrekthets- og utrullingsrisiko. Ikke valgt. |
| Cash-beregninger og rendering | Fire svar → state → memoiserte beregninger → DOM/paint | Beregningene er enkel aritmetikk over små objekter; ingen store lister eller synkrone løkker. | Ingen materiell flaskehals dokumentert. Ikke endret. |

Før endringen startet preloaderen dessuten `/api/nav/daily-cash`, som Cash-siden
aldri leser, mens `/api/dashboard/economic` (grunnlaget for de viktigste
cash-kortene) ventet til modulen var lastet og montert. De fire faktiske
ressursene starter nå parallelt med modulinnlastingen. Første komponentlasting
gjenbruker nøyaktig de samme pågående promise-ene; ordinær polling etter to
minutter går fortsatt direkte til API-et. `Promise.allSettled` og eksisterende
delvis-feilhåndtering er beholdt, slik at ett feilende endepunkt ikke skjuler de
andre svarene. Cachetiden er fortsatt 30 sekunder, og ingen datakontrakt er
endret.

Før/etter er kontrollert med samme statiske metode: opptelling av kall fra
brukerhandling til første komplette Cash-render, kontroll av URL-ene på begge
sider av modulgrensen og et bygg av produksjonspakken. Nettlesermåling mot et
produksjons-API er fortsatt nødvendig for å tallfeste spart veggklokketid; den
nedre grensen er modulens innlastingstid for økonomidata, mens mindre
nettverks-/backend-konkurranse kan gi ytterligere gevinst.

## Oppfølgingsfunn: Historikk og Brasil

Samme kontroll av alle rutene viste at Historikk og Brasil begge bruker live
økonomisk NAV i synlig innhold, men bare startet dette API-kallet etter at den
kode-splittede visningen var lastet, tolket og montert. Historikk trenger svaret
til «Dagens rabatt» og sammenligningen med medianen. Brasil trenger det til
BRL-følsomheten og Bemobis andel av NAV. Dermed kunne hoveddataene være på plass
mens disse nyttige feltene fortsatt viste tomme verdier.

| Kandidat | Startpunkt → sluttpunkt | Måling/estimat | Avhengighet og prioritering |
| --- | --- | --- | --- |
| Sent live-NAV-kall i Historikk og Brasil | Klikk/fokus/direkte rute → visningsmodul → økonomi-request → komplette nøkkeltall | Produksjonsbygget måler Historikk-chunken til 9,87 kB / 3,13 kB gzip og Brasil-chunken til 17,81 kB / 4,96 kB gzip. Kallet ventet på én ekstra modulnettverksrunde og parse/mount; anslått 50–200 ms på vanlig mobilnett, mer ved høy latenstid. | Økonomi-API-et har ingen parametere eller dataavhengighet fra visningsmodulen eller visningens andre request. Høy sikkerhet, lav risiko og liten endring. **Valgt.** |
| Forhåndslaste alle oversiktsdata ved retur | Menyfokus/hover → seks API-svar → komplett oversikt | Kan skjule deler av ventetiden ved bevisst hover, men kan starte opptil seks unødvendige kall når brukeren bare undersøker menyen. | Middels effekt og større nettverks-/backendrisiko. Ikke valgt. |
| Legge rabatt-historikk i bootstrap | Før HTML/JS → samlet bootstrap → median synlig | Fjerner ett separat førstesidekall, men øker den høyest prioriterte responsen for alle brukere og kobler ulik cachelevetid. | Lavere forhold mellom effekt og risiko. Ikke valgt. |

Begge eksisterende kall startes nå i `preload(view)`, samtidig med modul og øvrige
visningsdata. Polling-hookene brukte allerede den delte request-funksjonen, så de
gjenbruker samme promise ved montering. Antall requests er uendret: endringen
flytter to eksisterende kall tidligere og oppretter ingen nye datakontrakter.
30-sekunders navigasjonscache, HTTP-feilhåndtering og senere polling er uendret.

Før/etter er kontrollert med samme statiske metode og produksjonsbygg. Før var
stien `handling → modul → økonomi-request → komplett innhold`; etter er den
`handling → modul og økonomi-request parallelt → komplett innhold`. En
kontrakttest låser både tidlig request-start og gjenbruk i Historikk-hooken.

## Oppfølgingsfunn: Bemobi-eksponering i tilbakekjøpsvisningen

Gjennomgangen av den siste gjenværende direkte datahentingen i aktive visninger
fant at tilbakekjøpssiden viser Bemobi-aksjer per 1 000 Otello-aksjer, men starter
grunnlagskallet først etter at den kode-splittede siden er lastet og montert.

| Kandidat | Startpunkt → sluttpunkt | Måling/estimat | Avhengighet og prioritering |
| --- | --- | --- | --- |
| Sent Bemobi-kall i tilbakekjøpsvisningen | Klikk/fokus/direkte rute → Buyback-modul → Bemobi-request → komplett eksponeringsfelt | Produksjonsbygget måler Buyback-chunken til 15,49 kB / 4,34 kB gzip. Kallet ventet dermed på én modulnettverksrunde samt parse og montering; anslått 50–200 ms på vanlig mobilnett. | Bemobi-kallet har ingen parameter eller resultatavhengighet til modulen eller tilbakekjøpskallet. Høy sikkerhet, svært lav risiko og liten endring. **Valgt.** |
| Slå Bemobi-data sammen med tilbakekjøpsresponsen | Navigasjon → samlet backend-respons → komplett visning | Kan fjerne ett HTTP-kall, men krever en ny backend-kontrakt og kobler ulike cache- og feildomener. | Potensielt større gevinst, men klart høyere kompleksitet og korrekthetsrisiko. Ikke valgt. |
| Ytterligere klientberegning/rendering | To små svar → enkel divisjon → DOM/paint | Feltet bruker bare én divisjon og React-listene er små. | Ingen materiell flaskehals dokumentert. Ikke endret. |

Bemobi-requesten starter nå samtidig med Buyback-modulen og hovedrequesten.
Komponenten gjenbruker samme pågående promise, så request-antallet er fortsatt to
uavhengige kall totalt og ikke et preload-kall pluss et duplikat. Dermed endres
stien fra `handling → modul → Bemobi-request → komplett felt` til `handling →
modul og Bemobi-request parallelt → komplett felt`. Den delte funksjonen beholder
samme HTTP-statuskontroll, avviser ved feil og cacher bare vellykkede svar i 30
sekunder. Tilleggsfeltets eksisterende ikke-blokkerende feiloppførsel er også
beholdt.

Før og etter er kontrollert med samme statiske request- og avhengighetsanalyse og
produksjonsbygg. Endringen påvirker ikke chunkstørrelsen nevneverdig og fjerner
modulventingen fra requestens critical path. Faktisk spart veggklokketid bør
fortsatt verifiseres med nettlesermåling mot produksjons-API-et.

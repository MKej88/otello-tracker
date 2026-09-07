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

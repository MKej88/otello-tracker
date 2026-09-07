# Målrettet frontend-audit, 7. september 2026

## Critical path

Den faktiske førstesidestien er:

1. Nettleseren åpner `index.html` og starter preload av
   `/api/dashboard/bootstrap` før JavaScript-pakken.
2. React monterer `InvestorApp` og den ikke-kodesplittede `OverviewPage`.
3. Seks polling-hooks starter. Fire nyttige ressurser gjenbrukte bootstrap, mens
   rabatt-historikk og tilbakekjøpsstatus startet egne HTTP-kall.
4. Hver hook oppdaterer state når sin respons er ferdig; kortene rendres deretter
   uavhengig. Ingen blocking `await` mellom de seks kallene ble funnet.
5. Førstesiden har ingen store bilder, eksterne fonter eller lange tabeller. Det
   finnes derfor ikke dokumentasjon på at DOM, layout eller paint er flaskehalsen.

Sekundærvisninger er kode-splittet. Navigasjonens `preload` starter både modul og
nødvendige data før hash-ruten oppdateres, og et felles promise hindrer dupliserte
requests. NAV-periodene hentes i én materialisert pakke. Gjennomgangen fant ingen
reell avhengighet som tvinger datarequests til å vente på hverandre.

## Kandidater og prioritering

| Kandidat | Start → slutt | Måling/estimat | Vurdering |
| --- | --- | --- | --- |
| Separat tilbakekjøpskall på Oversikt | React effect → `overview-status` → state → synlig tilbakekjøpskort | 1 av 3 førsteskjermrequests. På gjenbesøk kunne kortet ikke bruke den synkrone nettlesercachen og måtte vente én full HTTP-respons, typisk minst én nettverksrunde (anslått 50–200 ms, mer ved Worker-oppstart). | Høy impact og sikkerhet, lav risiko. **Valgt.** |
| Rabatt-historikk utenfor bootstrap | React effect → historikkrespons → synlig median | 1 av 3 requests, opptil 72 punkter. Har annen cachetid og datastruktur enn øyeblikksbildet. | Middels mulig effekt, men større payload og risiko for foreldet snapshot. Ikke valgt. |
| Bundle/modulinnlasting | HTML → entry bundle → første React-render | Produksjonsbygget før endringen: ca. 217 kB JS / 69 kB gzip. Sekundærvisninger er allerede splittet; Oversikt er liten og nødvendig. | Lav forventet gevinst uten nettleserprofil. Ikke valgt. |
| React/DOM/databehandling | API-resultat → state → render → paint | Små lister og seks avgrensede state-oppdateringer; ingen stor synkron beregning på førstesiden. | Ingen dokumentert materiell flaskehals. Ikke endret. |
| Backend-latency | HTTP-start → API-respons | Bootstrap leser normalt ett ferdigberegnet D1-snapshot og rapporterer `server_ms`; live beregning er kun reserve. | Overvåkes, men ikke et frontendproblem på normalsti. |

Prioriteringen er effekt × sikkerhet ÷ risiko/kompleksitet. Ingen generell
memoisering eller refaktorering er gjort.

## Valgt forbedring

Tilbakekjøpsstatusen som Oversikt faktisk viser, er flyttet inn i det eksisterende
bootstrap-snapshotet. Den ubrukte prognosen i bootstrap er tatt ut; prognose-API-et
består uendret for detaljvisningen og andre klienter. Worker-endepunktet for
`overview-status` leser nå samme ferdigberegnede snapshot, og frontendens
request-samler leverer komponenten fra bootstrap eller fra siste gyldige
nettleserkopi.

Avhengigheten er kontrollert: tilbakekjøpsstatus, summary, economic, quotes og
events er uavhengige og bygges fortsatt parallelt uten sekvensielle `await`.
Snapshot- og nettleskcacheversjonene er økt, slik at gamle payloads aldri tolkes
som den nye formen. Feil i bootstrap faller fortsatt tilbake til det ordinære
endepunktet, og nettverksrevalidering erstatter en eventuell siste-gode kopi.

## Før og etter

Samme statiske request-opptelling på førstesiden:

- Før: **3 HTTP-kall** (`bootstrap`, rabatt-historikk og tilbakekjøpsstatus).
- Etter: **2 HTTP-kall** (`bootstrap` og rabatt-historikk), altså **33 % færre**.
- På gjenbesøk: tilbakekjøpskortet kan nå få siste-gode verdi på første
  React-render i stedet for først etter en separat respons.
- Produksjonsbuild etter endringen: **216,90 kB JS / 68,56 kB gzip**, i praksis
  uendret.

En faktisk millisekundmåling av LCP/INP var ikke praktisk mulig fordi miljøet ikke
har Chrome/Chromium. Tidsgevinsten er derfor oppgitt som fjernet nettverksrunde,
ikke som en påstått laboratoriemåling.

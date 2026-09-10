# Critical-path-audit av frontend, 10. september 2026

## Metode

Gjennomgangen fulgte standardinngangen og navigasjon mellom visninger:

`HTML → inngangspakke → routing → visningsmodul → API → state → React → DOM`

Produksjonsbygget ble kjørt før og etter med samme Vite-kommando. Requestrekkefølgen
ble kontrollert i kildekoden. Miljøet har ikke Chrome eller Chromium, så layout og
paint er ikke profilert. Tidsvirkningen nedenfor er derfor en kritisk-sti-estimering,
ikke en påstått produksjonsmåling.

## Kandidater

| Kandidat | Startpunkt → sluttpunkt | Faktisk tillegg | Avhengighet og vurdering |
| --- | --- | --- | --- |
| Sen oppdagelse av standardvisningen | Inngangspakken er ferdig lastet og kjørt → dynamisk import oppdages → JavaScript og CSS for Oversikt hentes → React kan vise nyttig innhold | Oversikt krevde to sent oppdagede filer (12,92 kB JavaScript / 3,92 kB gzip og 7,98 kB CSS / 1,77 kB gzip). På tom cache tilføyde dette minst én request-rundtur etter inngangspakken, pluss overføring og behandling. Ved 100 ms rundtur er den fjernbare ventingen minst omtrent 100 ms. | Oversikt er standardruten og kan ikke rendres uten modulen. Høy effekt på første besøk, høy sikkerhet og lav kompleksitet. Kostnaden er ca. 5,1 kB mer gzip på direkte inngang til en annen hash-rute. **Valgt.** |
| API-kall på Oversikt | HTML-preload → bootstrap/historikk → hooks → state → render | Fem sentrale svar er samlet i bootstrap, rabattdata prelastes separat, og siste gode bootstrap kan rendres synkront på gjenbesøk. | Kallene starter parallelt før React og har ingen dokumentert ny waterfall. Backendens `server_ms` skiller serverarbeid fra frontendventing. Ikke endret. |
| Navigasjon til andre visninger | Klikk/fokus/hover → modul og data → render | Ved klikk starter modul og nødvendige data før hash-ruten oppdateres. Samtidige kall til samme URL gjenbrukes. | Kodeinnlasting blokkerer ikke datahenting. Ingen materiell sekvensiell venting dokumentert. Ikke endret. |
| Klientberegning og React | API-svar → databehandling → state → render → DOM | Listene er små, og de relevante beregningene er enten enkle eller memoiserte. Hele produksjonsbygget tok 0,56–0,59 sekunder, men byggetid måler ikke rendertid. | Uten en nettleserprofil finnes det ikke grunnlag for å kalle dette en materiell flaskehals. Ikke endret. |

## Valgt forbedring

Oversikt importeres nå som en del av inngangspakken. Nettleseren trenger dermed ikke
vente til routingkoden er lastet, tolket og kjørt før den oppdager JavaScript og CSS
som kreves for standardvisningen. API-preload, caching og feilhåndtering er urørt.
Andre, sjeldnere visninger beholder kode-splitting.

## Før og etter

- **Før:** inngang 203,20 kB / 64,73 kB gzip, deretter en ny requestfase for
  Oversikt-JavaScript (12,92 kB / 3,92 kB gzip) og CSS (7,98 kB / 1,77 kB gzip).
- **Etter:** én inngangsfase på 217,46 kB / 68,73 kB gzip og 39,94 kB / 7,70 kB
  gzip CSS; ingen separat Oversikt-chunk.
- Den totale komprimerte overføringen er omtrent uendret. Standardinngangen fjerner
  to sent oppdagede requests og minst én nettverksrundtur fra tiden til nyttig innhold.
- Direkte inngang til en annen hash-rute laster omtrent 5,1 kB gzip som den ruten
  ikke trenger. Det er den kjente avveiningen og grunnen til at bare standardvisningen
  er tatt inn i inngangspakken.

En produksjonskontroll i nettleserens Network-panel bør bekrefte at det ikke lenger
kommer en egen `OverviewPage`-request etter inngangspakken, og sammenligne tid til
NAV-kortet vises på tom cache.

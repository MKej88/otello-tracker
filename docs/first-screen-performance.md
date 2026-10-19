# Syntetisk ytelsesovervåking av OtelloTracker

## Arkitektur

Ytelsesovervåking kjøres fra **GitHub Actions**, ikke inne i investorgrensesnittet.
Workflowen `.github/workflows/production-performance.yml` utføres automatisk
to ganger daglig (07:15 og 19:15 UTC) og kan startes manuelt med
`workflow_dispatch`.

Fra en GitHub-runner hentes offentlig produksjons-API direkte og et nytt,
tomt Chromium/Chrome-profilvindu åpnes for **alle 12 hovedvisninger**:
Oversikt, NAV, NAV-sensitivitet, Historikk, Tilbakekjøpsprogram, Cash,
Bemobi, BRL/NOK, Brasil, Konsensus, Nyheter og Datakvalitet.

Dette gir **syntetiske nettlesermålinger per side** av tiden til hoveddata vises,
og måling av HTML-dokumentets TTFB, DOM-klart-tid og de tregeste
same-origin API-kallene ved førstegangsinnlasting.

I tillegg brukes én nettleserøkt til å klikke gjennom alle 12 hovedvisningene
fra hovedmenyen, uten full sidelasting. For hvert sideskifte måles tiden fra
klikk til relevant hovedinnhold er synlig, med tregeste API-kall. Dermed
skilles **kald, direkte innlasting** fra **intern SPA-navigering**.

Direkte API-prober kjøres tre ganger per endepunkt, med relevante kilder
til blant annet NAV, historikk, tilbakekjøp, Bemobi, Brasil, valuta, nyheter
og datakvalitet. Tid til responsheadere (nettverksobservert TTFB)
og tid til fullført nedlasting rapporteres separat, sammen med responsstørrelse.
Dette er **ikke** ren Cloudflare Worker CPU-tid eller D1-spørringstid.

## Hvor finnes resultatene?

Åpne GitHub Actions → **Production performance (synthetic)**.
Hver kjøring skriver en oversikt i **Job summary** og arkiverer en maskinlesbar
`performance-report.json` som workflow-artifact i 30 dager.

## Historikk, 7-dagers median og varsler

Etter hver vellykkede produksjonsmåling leser
`frontend/tools/performance-trends.mjs` tidligere
`otello-production-performance`-artifacts fra de siste 14 dagene, med
GitHub API og jobbens innebygde `GITHUB_TOKEN` (`actions: read`).
Kun kjøringer fra `main` brukes som historiske produksjonspunkter;
målinger fra PR-er forurenser ikke sammenligningsgrunnlaget.

Rapporten viser separat for alle de 12 visningene:
- Median for **kald direkte innlasting** i siste 7 dager mot foregående 7 dager.
- Median for **intern navigering** i siste 7 dager mot foregående 7 dager.
- Differanse i prosent og antall observasjoner i hver periode.
- Tilsvarende trend for de 12 direkte API-målepunktene.

Det kreves minst **seks vellykkede målinger på minst tre ulike dager
i hver 7-dagersperiode** før en prosentendring tolkes som pålitelig
nok til å varsle. Trendvisningen kan vise mediansvar selv ved færre
observasjoner, men endringskolonnen får `–` og varsling er deaktivert
fram til kravet er oppfylt. Dette skjer først etter at minst to uker med
produksjonshistorikk er samlet opp.

**Bekreftet forverring** krever både en stor medianendring og at de
to siste målingene fortsatt er tydelig tregere enn forrige ukes median:

| Måletype | Relativ økning | Absolutt økning | Ny median |
| --- | ---: | ---: | ---: |
| Direkte lasting | minst 35 % | minst 500 ms | minst 1 000 ms |
| Sideskifte | minst 35 % | minst 300 ms | minst 600 ms |
| API | minst 45 % | minst 150 ms | minst 250 ms |

Ved bekreftet forverring opprettes en **GitHub Actions-advarsel** med
side/endepunkt og endring. Planlagte `main`-kjøringer markeres
dessuten **failed**, slik at GitHubs vanlige workflow-feilvarsler
kan utløses når brukeren har aktivert slike varsler. Manuelle tester
og lokale PR-tester feiler ikke på produksjonsforverringer som kan være
uavhengige av endringene.

**PR-kontroller kjører bare syntaksvalidering og trend-enhetstester, uten
produksjonsforespørsler.** Dette begrenser unødvendig trafikk mot Cloudflare
ved mange raske kodeendringer. Selve ytelsesmålingen kjøres bare ved
planlagt eller manuelt utløst workflow.

Trenddata legges inn under `trend` i samme JSON-artifact. Dersom
GitHub API er utilgjengelig, vises dette som `Begrenset historikk`;
den planlagte målingen feiler ikke kun på grunn av manglende historikk.

Manglende hoveddata, feil HTTP-status eller testtimeout feiler jobben.
En førsteside som bruker over fem sekunder genererer en GitHub-advarsel,
men ikke automatisk feil, fordi nettverk og runnerbelastning kan variere.

Ingen målinger blir lagt inn i Datakvalitet-visningen eller sendt fra
besøkendes nettlesere. Denne overvåkingen krever ingen Cloudflare-hemmeligheter.

## Begrensninger

- Dette er et eksternt, syntetisk testsystem, ikke Real User Monitoring.
- Målingene påvirkes av hvor GitHub-runneren kjører, ruting, cache og nettverk.
- Antall daglige kjøringer er for lavt til en pålitelig P95 for alle besøkende.
- Alle 12 rutene åpnes med tom profil for å fange opp treg førstegangslasting.
- En rute markeres som klar når rutespesifikt hovedinnhold finnes etter
  React-rendering. Noen sekundærkort eller diagrammer kan lastes etter dette.
- SPA-navigering måles i én sammenhengende økt; senere sider kan nyte godt av
  kode- og API-cache som allerede er lastet av tidligere visninger.
- Nye hovedvisninger må legges til i målekatalogen, ellers måles de ikke.
- For å evaluere reell brukeropplevelse kan man kombinere målingene
  med aggregerte Cloudflare Web Analytics, uten å vise dem i investordashboardet.

## API-effektivitet og polling

Ytelsestiltak fra forrige runde er videreført:
- Polling stoppes når nettleserfanen ikke er synlig.
- Når fanen blir synlig, kontrolleres data umiddelbart.
- Markedsdata beholder kortere oppdateringsintervall.
- Historikk, tilbakekjøpsstatus og kommende hendelser på oversikten
  oppdateres hvert 15. minutt mens fanen er synlig.

Hvis det er behov for D1-query-timing eller rene Worker-kjøretider,
må dette måles separat med instrumentering i Worker eller via
Cloudflare sin egen Workers-observability.

# Syntetisk ytelsesovervåking av OtelloTracker

## Arkitektur

Ytelsesovervåking kjøres fra **GitHub Actions**, ikke inne i investorgrensesnittet.
Workflowen `.github/workflows/production-performance.yml` utføres automatisk
to ganger daglig (07:15 og 19:15 UTC) og kan startes manuelt med
`workflow_dispatch`.

Fra en GitHub-runner hentes offentlig produksjons-API direkte og et nytt,
tomt Chromium/Chrome-profilvindu åpnes for hver av rutene:
- `https://otellotracker.com/#oversikt`
- `https://otellotracker.com/#brasil`

Dette gir **syntetiske nettlesermålinger** av tiden til hoveddata vises på skjermen,
og måling av HTML-dokumentets TTFB, DOM-klart-tid og de tregeste
same-origin API-kallene ved innlasting.

Direkte API-prober kjøres tre ganger per endepunkt:
`/api/health`, `/api/dashboard/bootstrap`, `/api/dashboard/economic`
og `/api/brazil/dashboard`. Tid til responsheadere (nettverksobservert TTFB)
og tid til fullført nedlasting rapporteres separat, sammen med responsstørrelse.
Dette er **ikke** ren Cloudflare Worker CPU-tid eller D1-spørringstid.

## Hvor finnes resultatene?

Åpne GitHub Actions → **Production performance (synthetic)**.
Hver kjøring skriver en oversikt i **Job summary** og arkiverer en maskinlesbar
`performance-report.json` som workflow-artifact i 30 dager.

Manglende hoveddata, feil HTTP-status eller testtimeout feiler jobben.
En førsteside som bruker over fem sekunder genererer en GitHub-advarsel,
men ikke automatisk feil, fordi nettverk og runnerbelastning kan variere.

Ingen målinger blir lagt inn i Datakvalitet-visningen eller sendt fra
besøkendes nettlesere. Denne overvåkingen krever ingen Cloudflare-hemmeligheter.

## Begrensninger

- Dette er et eksternt, syntetisk testsystem, ikke Real User Monitoring.
- Målingene påvirkes av hvor GitHub-runneren kjører, ruting, cache og nettverk.
- Antall daglige kjøringer er for lavt til en pålitelig P95 for alle besøkende.
- Begge rutene åpnes med tom profil for å fange opp treg førstegangslasting.
- Hoveddata markeres når Oversikts-NAV eller Brasils makrokort finnes
  etter React-rendering; øvrige sider kan fremdeles laste etter dette.
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

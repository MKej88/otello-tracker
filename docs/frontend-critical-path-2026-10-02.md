# Undersøkelse av frontendens critical path (2026-10-02)

## Metode

Gjennomgangen fulgte direkte åpning og intern navigasjon gjennom routing,
modulinnlasting, API-kall, klientcache, state og rendering. Produksjonsbygget ble
brukt til å måle overføringsmengden før og etter med samme Vite-oppsett. Miljøet
har ikke en tilgjengelig Chrome/Chromium-installasjon, så layout og paint er ikke
profilert og det oppgis ikke oppdiktede tidsmålinger.

## Dokumentert flaskehals

`OverviewPage` var importert direkte i inngangspakken. Dermed måtte alle direkte
ruter laste, parse og kompilere Oversikt-kode og -stil før React kunne vise den
valgte siden, selv om bare Oversikt bruker disse ressursene.

Startpunktet var nedlasting av inngangspakken, og sluttpunktet var at React kunne
starte rendering av den valgte visningen. Før endringen var inngangspakken 76,65
kB gzip JavaScript og 9,18 kB gzip CSS. Etter utskilling er den 72,45 kB og 7,87
kB. Andre direkte ruter unngår dermed 5,51 kB gzip i sin blokkerende inngangsvei,
en reduksjon på 6,4 prosent av disse to inngangsressursene. Faktisk spart tid
avhenger av nettverk og enhet; byteforskjellen er målt, ikke omregnet til et
udokumentert millisekundtall.

## Kandidater og prioritering

| Kandidat | Start → slutt | Målt/estimert tillegg | Impact × confidence ÷ risiko |
| --- | --- | --- | --- |
| Oversikt i alle ruters inngangspakke | Inngangspakke → React kan rendre aktiv rute | 5,51 kB gzip unødvendige blokkerende ressurser, 6,4 % | middels × høy ÷ lav — valgt |
| API-kall ved intern navigasjon | Klikk → data i state | Modul og data startes allerede sammen, og pågående kall gjenbrukes | lav × høy ÷ middels — ikke endret |
| React/databehandling | API-svar → DOM | Små synlige lister og enkle/memoiserte avledninger; ingen materiell blokkering dokumentert | lav × middels ÷ middels — ikke endret |
| Backend-latens | Request → svar | Hot snapshot, cache og 750 ms sikret fallback finnes allerede; produksjonslatens er ikke målt lokalt | ukjent × lav ÷ høy — ikke endret |

## Valgt forbedring og avhengigheter

Oversikt lastes nå som de øvrige kode-splittede visningene. For direkte inngang
til en annen rute lastes den ikke. For Oversikt kalles modulinnlastingen helt i
starten av eksisterende `preload(initialView)`, før React rendres, mens HTML-en
fortsatt starter de nødvendige datarequestene før inngangspakken. Ved intern
navigasjon starter modul og data i samme `preload`-kall før hash-ruten endres.

Det finnes ingen dataavhengighet mellom Oversikt-modulen og API-kallene, og
endringen serialiserer dem derfor ikke. API-URL-er, klientcache, polling,
revalidering og feilhåndtering er uendret. Avveiningen er én liten separat
modulrequest for Oversikt; den startes tidlig og kan gå parallelt med dataene.

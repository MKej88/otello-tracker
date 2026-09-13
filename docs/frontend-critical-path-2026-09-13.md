# Undersøkelse av frontendens critical path (2026-09-13)

## Metode

Jeg fulgte direkte innlasting og intern navigasjon fra HTML/ruting, via
modulinnlasting og API-kall, til komponentenes state-oppdateringer og rendering.
Produksjonsbygget ble brukt til å kontrollere buntstørrelser. Requestrekkefølgen
ble kontrollert fra rutens `preload()` og sidenes data-hooks. Dette er en
kodebasert måling; produksjonslatens ble ikke lagt til grunn for valget.

## Materiell flaskehals

Ved tastaturnavigasjon startet fokus på hver menyknapp umiddelbart all
forhåndshenting for den visningen. Startpunktet var `focus`-hendelsen, og
sluttpunktet var at rutens modul- og API-requests var startet. En bruker som
tabbet gjennom menyen kunne dermed starte requestene til visninger brukeren
aldri åpnet, før requestene til den valgte visningen fikk arbeidsro.

Med dagens tolv visninger kunne én rask gjennomgang av menyen starte opptil 14
individuelle API-URL-er, én samlet NAV-periode-request og elleve kode-splittede
moduler. Før endringen var antallet etter rask gjennomtabbing 14 API-URL-er +
NAV-bunten; etter endringen er det 0 så lenge hvert fokus varer kortere enn 120
ms. Klikk eller Enter starter fortsatt valgt visnings modul og data umiddelbart.
Ved en bevisst pause på en knapp starter forhåndshentingen etter 120 ms.

Avhengigheten var ikke reell: fokus betyr ikke at ruten er valgt. Den valgte
ruten trenger bare sine egne requests, og `selectView()` starter dem uansett før
hash-rutingen. Endringen flytter derfor ikke en nødvendig request bak en annen.
Eksisterende request-sammenslåing, 30-sekunders cache og feilbehandling er
uendret.

## Vurderte kandidater

| Kandidat | Start → slutt | Målt/estimert tillegg | Impact × confidence ÷ risiko | Valg |
| --- | --- | --- | --- | --- |
| Umiddelbar preloading ved hvert tastaturfokus | fokus → unødvendige modul/API-starter | opptil 14 API-URL-er + NAV-bunt og 11 moduler før valgt rute | høy × høy ÷ lav | implementert |
| NAV-bunten venter på synlig 1M-periode | første periodesvar → øvrige perioder | 0 ms for synlig standardinnhold | lav × høy ÷ middels | beholdt |
| Kode-splittede rutemoduler | valg → modul ferdig | største rutebunt 6,22 kB gzip | lav × høy ÷ middels | beholdt |
| Klientberegning og rendering | API-svar → nyttig DOM | grafer bruker høyst 72 punkter; ingen materiell blokkering funnet | lav × middels ÷ middels | beholdt |
| Backend-latens | request → svar | ikke målt; hot snapshot brukes på førstesiden | ukjent × lav ÷ høy | ingen endring |

## Resultat og korrekthet

Mus og tastatur bruker nå samme korte intensjonsforsinkelse. `blur` og
`mouseleave` avbryter arbeid som ikke lenger er ønsket. Aktivering av knappen
avbryter timeren og starter riktig preload synkront gjennom eksisterende
`selectView()`. Dataformat, caching, state-oppdateringer og feilhåndtering er
ikke endret.

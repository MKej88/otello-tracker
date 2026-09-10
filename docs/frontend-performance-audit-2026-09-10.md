# Målrettet frontend-audit, 10. september 2026

## Metode og critical path

Gjennomgangen fulgte både førstegangsbesøk og navigasjon mellom visningene:

`klikk/hash → InvestorApp → dynamisk modul + data-preload → React effect → API → state → render`

Produksjonsbygget ble brukt for å måle modulstørrelser. Requestrekkefølgen og
state-oppdateringene ble kontrollert i kildekoden. Miljøet har ikke Chrome eller
Chromium, så DOM-, layout- og paint-tid kunne ikke måles med en nettleserprofil.
Veggklokkeeffekten under er derfor uttrykt direkte fra await-avhengigheten, ikke
som en påstått produksjonsmåling.

Ruting og navigasjon starter allerede kode og nødvendige API-kall parallelt.
`fetchPreloadedJson` samler dessuten samtidige kall til samme URL. Det ble ikke
funnet dokumentasjon på tung klientberegning, layout eller unødvendige renders
som sannsynligvis dominerer ventetiden.

## Kandidater

| Kandidat | Startpunkt → sluttpunkt | Måling/estimat | Avhengighet og vurdering |
| --- | --- | --- | --- |
| Valgfritt tilbakekjøpskall blokkerte Cash | Navigasjon til Cash → fire parallelle API-kall → `Promise.allSettled` venter på det tregeste → tre kjernesvar settes i state → nyttig cash-innhold rendres | Før var tid til kjerneinnhold `max(summary, bemobi, economic, buyback)`. Etter er den `max(summary, bemobi, economic)`. Spart tid er derfor `max(0, buyback − tregeste kjernekall)`: 600 ms dersom kjernen tar 100 ms og tilbakekjøp tar 700 ms, og potensielt hele timeout-perioden ved heng. | Cash-visningen krever summary, Bemobi og economic. Koden klassifiserer allerede buyback som et delvis tillegg, og kalkulatoren håndterer manglende buyback. Høy effekt når tilleggskallet er tregt, høy sikkerhet og lav risiko. **Valgt.** |
| Førstesidens API-kall | HTML-preload → bootstrap → seks ressurs-hooks → render | Bootstrap samler fem svar, mens historikk prelastes separat. Inngangspakken er 203,20 kB / 64,72 kB gzip; Oversikt-modulen er 12,92 kB / 3,92 kB gzip. | Kallene starter tidlig og parallelt, og sist-gode data kan vises før nettverket svarer. Ingen ny materiell waterfall ble dokumentert. Ikke endret. |
| Kode-splittede visninger | Klikk → dynamisk import → komponentmount | Visningsmodulene er 9,11–24,06 kB ukomprimert. Data-preload startes samtidig med import ved klikk, fokus eller tilsiktet hover. | Modulen blokkerer ikke starten på datahenting. Mer ivrig lasting ville bruke nettverk på visninger brukeren kanskje aldri åpner. Lav forventet effekt og større risiko for konkurranse. Ikke endret. |
| React/klientberegning | State update → render → DOM/paint | Komponentene bruker små tabeller/lister og lokal aritmetikk; produksjonsbygget fullføres på under ett sekund i dette miljøet. | Ingen nettleserprofil eller kodefunn dokumenterer en materiell CPU-flaskehals. Ikke endret. |
| Backend-latency | Request start → API-svar | Kan fortsatt dominere hvert enkelt kall. Frontendendringen fjerner bare unødvendig venting på et uavhengig tilleggskall. | Servermåling må gjøres i produksjon for å skille Worker-/databaseventing fra nettverk. Ingen backendendring uten slik dokumentasjon. |

## Valgt forbedring

De tre svarene som faktisk kreves for Cash, ferdigstilles og publiseres nå uten å
vente på tilbakekjøpsdata. Tilbakekjøpskallet starter fortsatt samtidig, får samme
30-sekunders navigasjonscache og samme to-minutters oppdatering, men oppdaterer
den valgfrie kalkulatorinformasjonen separat når det er klart.

Datakorrektheten er bevart: siden viser fremdeles ikke hovedinnhold før alle tre
kjernesvar finnes. Feil i et kjernesvar gir samme feiltilstand, mens feil i
tilbakekjøpskallet fortsatt gir varsel om delvis manglende data og beholder siste
gode verdi.

## Før og etter

Samme deterministiske ventemodell gir:

- **Før:** kjerne 100 ms, tilbakekjøp 700 ms → nyttig Cash-innhold etter 700 ms.
- **Etter:** de samme kallene → nyttig Cash-innhold etter 100 ms; kalkulatortillegg
  etter 700 ms.
- **Forbedring i eksempelet:** 600 ms, eller 86 % kortere tid til korrekt
  kjerneinnhold.
- **Når alle kall er like raske:** praktisk talt ingen forskjell.

Produksjonens Network- og Performance-panel bør brukes som oppfølging for å
måle faktisk fordeling og backend-latency under reelle nettverksforhold.

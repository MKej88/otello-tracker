# Critical-path-audit av frontend, 12. september 2026

## Metode

Gjennomgangen fulgte både standardinngangen og direkte inngang til hver hash-rute:

`HTML → preload → inngangspakke → routing → visningsmodul + API → state → React → DOM`

Requestrekkefølgen ble kontrollert i HTML- og React-koden. Produksjonsbygget ble
kjørt etter endringen. Miljøet har ikke Chrome eller Chromium, så layout og paint
er ikke profilert, og faktisk produksjonslatens er ikke fremstilt som lokalt målte
millisekunder.

## Kandidater

| Kandidat | Startpunkt → sluttpunkt | Tilført tid / mengde | Avhengighet og vurdering |
| --- | --- | --- | --- |
| Oversikt-requests på alle direkte ruter | HTML-parseren ser preload → bootstrap og rabatt-historikk hentes med høy/lav prioritet → den valgte rutens modul og API konkurrerer om nettverk og server | **To unødvendige API-kall** ved direkte inngang til hver av de 11 andre visningene. Tilført veggklokketid er nettverksavhengig, men bootstrap hadde eksplisitt høy prioritet og kunne derfor konkurrere direkte med nyttig innhold. | Ingen annen visning leser disse svarene før eventuell senere navigasjon til Oversikt. Høy sikkerhet, lav kompleksitet og lav datarisiko. **Valgt.** |
| Kode-splittede visninger | Ruting → modul → render | Modulene er små, og deres datarequests startes samtidig med modulene. | Ingen falsk modul→data-avhengighet ble funnet. Ivrigere lasting kan konkurrere med aktiv rute. Ikke endret. |
| Requests inne i visningene | Navigasjonspreload → effect → state | Pågående kall gjenbrukes i 30 sekunder. Cash skiller allerede valgfritt tilbakekjøpsgrunnlag fra kjerneinnhold. | Ingen ny duplikat eller materiell sekvens ble dokumentert. Ikke endret. |
| Klientberegning, React og DOM | API-svar → state → render → paint | Synlige lister er små, og sentrale avledninger er enkle eller memoiserte. | Uten nettleserprofil finnes det ikke grunnlag for en risikofylt renderoptimalisering. Ikke endret. |
| Backend-latens | Request → respons | Kan dominere ved Worker-/databaseventing. | Den valgte endringen unngår to hele backend-kall der svarene ikke kan bidra til aktiv visning. Ingen backendendring uten produksjonsmåling. |

## Valgt forbedring

HTML-en starter nå Oversikt-preloadene bare når URL-en faktisk åpner Oversikt
(tom hash eller `#oversikt`). På andre direkte ruter får visningsmodulen og dens
egne datarequests nettverket for seg selv. På Oversikt starter begge preloadene
fortsatt under HTML-parsing, før hovedpakken, med samme URL, prioritet og
credentials som før. Derfor svekkes verken request-gjenbruk, caching eller
feilhåndtering.

Den lille inline-koden tillates med en konkret SHA-256-hash i begge eksisterende
Content Security Policy-konfigurasjonene. `unsafe-inline` er ikke åpnet for
skript. En test beregner hashen fra faktisk HTML og låser at begge leveringsveier
har korrekt verdi.

## Før og etter

- **Før, direkte annen rute:** to Oversikt-kall startet før ruteren, i tillegg til
  den aktive visningens modul og data.
- **Etter, direkte annen rute:** null Oversikt-kall. Det er en reduksjon på to av
  to irrelevante kall (100 %).
- **Før og etter, Oversikt:** to tidlige preload-kall med uendrede URL-er og
  prioriteringer; nyttig førstesideinnhold beholder samme nettverksplassering.
- **Kjent avveining:** en svært liten synkron hash-sjekk kjøres i `<head>`. Den
  inneholder ingen nettverk, databehandling eller DOM-lesing som kan utløse layout.

En enkel produksjonskontroll er å åpne for eksempel `/#brasil` med tom cache og
bekrefte i Network-panelet at `dashboard/bootstrap` og `discount-history` ikke
sendes. Ved `/#oversikt` skal begge fortsatt starte før JavaScript-pakken.

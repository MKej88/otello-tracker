# Critical-path-audit: navigasjon til NAV, 10. september 2026

## Metode

Gjennomgangen fulgte navigasjon til NAV:

`klikk/fokus → routing-preload → modul- og API-request → state → React → DOM`

Requestrekkefølgen ble kontrollert med en deterministisk test der svaret for den
synlige perioden holdes tilbake. Produksjonsbygget ble kjørt med samme kommando før
og etter. Miljøet har ikke Chrome eller Chromium, så layout og paint er ikke
profilert og det oppgis ingen konstruert nettlesertid.

## Kandidater

| Kandidat | Startpunkt → sluttpunkt | Tilført tid | Avhengighet og vurdering |
| --- | --- | --- | --- |
| Alle NAV-perioder blokkerte første periode | Brukeren velger NAV → `/api/dashboard/nav-periods` lastes → hele bunten parses → 1 M legges i state → nyttig periodeinnhold rendres | Før måtte seks perioder, hver med opptil 72 punkter, overføres før 1 M kunne vises. Det er opptil 432 punkter før de opptil 72 synlige punktene kan brukes. Ventingen er hele forskjellen mellom responstiden til bunten og ett periodesvar. | 1 M-visningen trenger bare 1 M. De fem andre periodene er kun nødvendige etter et senere valg. Høy effekt under tregt nettverk, høy sikkerhet, lav risiko. **Valgt.** |
| Kode-splittet NAV-modul | Klikk → modulrequest → React-mount | Produksjonsmodulen er 14,97 kB / 4,57 kB gzip. | Data starter allerede parallelt med modulen. Å legge NAV i inngangspakken vil belaste alle som bare bruker standardvisningen. Lavere impact × confidence / risiko. |
| React og klientberegning | API-svar → state → render → DOM | Maksimalt 72 punkter for valgt periode og enkle, memoiserte beregninger. | Ingen profil eller kodefunn dokumenterer en materiell CPU-/renderflaskehals. Ikke endret. |
| Backend | Request → API-svar | Materialiserte periodesvar leses fra cache; faktisk D1-/Worker-tid er ikke tilgjengelig lokalt. | Frontend skal ikke vente på fem ubrukte payload-deler uansett backendtid. Ingen backendendring. |

## Valgt forbedring

Den synlige standardperioden (1 M) hentes nå først fra det eksisterende,
materialiserte periodeendepunktet. Først når den requesten er ferdig, lastes bunten
med de fem andre periodene i bakgrunnen. NAV-modulen lastes fremdeles parallelt med
1 M-dataene, og komponenten gjenbruker samme request i stedet for å duplisere den.

Datakorrekthet og feilbehandling er uendret: samme API-payload brukes for 1 M,
request-cache og statuskontroll beholdes, og de andre periodene har fortsatt
fallback til sine eksisterende endepunkter dersom bunten mangler eller er ugyldig.

## Før og etter

Den deterministiske testen viser requestrekkefølgen med identisk metode:

- **Før:** NAV-bunten startet først, og 1 M var avledet av dette svaret.
- **Etter:** bare 1 M-requesten er i flight på den synlige periodens critical path;
  NAV-bunten starter etterpå.
- **Reduksjon på critical path:** fra opptil seks perioder / 432 historikkpunkter
  til én periode / 72 punkter, altså opptil 83 % færre periodepunkter før nyttig
  innhold kan vises.
- JavaScript-bygget er praktisk talt uendret: inngang 217,56 kB / 68,77 kB gzip,
  NAV-modul 14,97 kB / 4,57 kB gzip.

Faktisk millisekundgevinst bør følges opp i produksjonens Network-panel, fordi den
avhenger av payload-komprimering, nettverk og Worker-/D1-latens.

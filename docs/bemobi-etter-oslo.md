# Bemobi siden Oslo stengte

Oversikten viser kursendringen i BMOB3 i BRL fra siste Oslo-slutt til siste
tidsstemplede Bemobi-kurs. Den inkluderer ikke BRL/NOK eller forventet OTEC-kurs.

Cloudflare-endepunkt: `/api/market/bemobi-after-oslo`. Kortet hentes separat fra
førstesidens bootstrap og oppdateres hvert andre minutt. Eksisterende kursinnhenting
fortsetter hvert 30. minutt; referansejobben henter bare referansen.

## Referanse

- Ordinær sluttauksjon: 16:25 Europe/Oslo. Innlesing 16:40 med nye forsøk 16:41/16:42.
- Onsdag før påske: 13:05. Innlesing 13:20 med nye forsøk 13:21/13:22.
- UTC-cron dekker begge sommertidsalternativene; lokal kalender og klokke filtrerer
  irrelevante kjøringer før nettverkskall. Oslo- og B3-helligdager håndteres.
- Referansen er **omtrentlig**: B3s svarklokke minus oppgitt forsinkelse på 15 minutter.
  Dette er ikke et eksplisitt tidspunkt for siste handel. Tillatt avvik fra
  sluttauksjonen er tre minutter; faktisk referansetidspunkt vises.
- Svarklokken må være fersk (maksimalt 60 sekunder gammel; inntil fem sekunders
  klokkeavvik tillates). Gamle eller ugyldige svar gir ingen referanse.
- Referansen lagres uforanderlig per Oslo-dato i eksisterende `runtime_state` med
  nøkkel `bemobi_oslo_reference_v1:YYYY-MM-DD`. Ingen migrering er nødvendig.
- Jobben bruker eksisterende skriverlås og registrerer resultat i `job_runs`.
  Ved låsekonflikt eller kildefeil kan neste minutt forsøke igjen. Mangler alle
  forsøk, viser kortet at referansen mangler. Ingen gammel 30-minutterskurs erstattes
  som om den var kursen ved Oslo-slutt.
- På halve handelsdager kan B3 fortsatt være stengt ved Oslo-slutt. Når ingen
  fersk referanse finnes, vises manglende grunnlag fremfor en oppdiktet kurs.

## Seneste kurs og status

Beregn `(nyeste kurs / referansekurs - 1) * 100`. Bruk bare `LAST`-observasjoner
etter referansen og ikke senere enn faktisk klokke. `CLOSE` med syntetiske
dagstidspunkt brukes ikke. Nyeste kurstid vinner; B3 prioriteres ved lik kurstid,
med Yahoo som eksisterende sekundærkilde. Kurver viser lagrede observasjoner.

For gammel kurs under B3-handel, feil handelsdato eller nettverksfeil i kortet
undertrykker prosentvisningen. Utenfor B3s handelsvindu beholdes siste tilgjengelige
kurs og tidspunkt. Referansen beholdes til neste Oslo-slutt, også gjennom helg.
Når ny sluttauksjon er passert, venter kortet på den nye forsinkede referansen.

Endringen gjelder Cloudflare-produksjonsløsningen. Referanse-backendens lokale API
har ikke dette nye endepunktet eller cron-jobben.

Kilder: eksisterende `cloudflare/src/bmob3_ingestion.py` (B3-forsinkelse),
[Euronexts børsdagskalender](https://www.euronext.com/en/trading/trading-hours-holidays)
og [Oslo migration guidelines](https://connect2.euronext.com/sites/default/files/it-documentation/Oslo_Bors_Migration%20Guidelines%20-%20v2.3.1_0.pdf)
(sluttauksjon og halv dag). Kalenderreglene gjenbruker prosjektets Oslo-kalender.

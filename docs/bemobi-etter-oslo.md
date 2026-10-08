# Bemobi siden Oslo Børs stengte

Oversikten viser kursendringen i BMOB3 i BRL fra siste close på Oslo Børs til siste
tidsstemplede Bemobi-kurs. Ved siden av vises teoretisk OTEC-effekt fra Bemobi-bevegelsen alene. Valutabevegelser inngår ikke, og effekten er ingen prognose for OTEC-kursen.

Cloudflare-endepunkt: `/api/market/bemobi-after-oslo`. Kortet hentes separat fra
førstesidens bootstrap og oppdateres hvert andre minutt. Eksisterende kursinnhenting
fortsetter hvert 30. minutt; referansejobben henter bare referansen.

## Referanse

- Ordinær sluttauksjon: 16:25 Europe/Oslo. Innlesing forsøkes hvert minutt 16:37–16:43; bare referansetider innen tre minutter fra sluttauksjonen godtas.
- Onsdag før påske: 13:05. Innlesing forsøkes 13:17–13:23 med samme tidsvalidering.
- UTC-cron dekker begge sommertidsalternativene; lokal kalender og klokke filtrerer
  irrelevante kjøringer før nettverkskall. Oslo- og B3-helligdager håndteres.
- Referansen er **omtrentlig**: B3s svarklokke minus oppgitt forsinkelse på 15 minutter.
  Dette er ikke et eksplisitt tidspunkt for siste handel. Tillatt avvik fra
  sluttauksjonen er tre minutter; faktisk referansetidspunkt vises.
- Svarklokken må være fersk (maksimalt 60 sekunder gammel; inntil fem sekunders
  klokkeavvik tillates). Gamle eller ugyldige svar gir ingen referanse.
- Referansen lagres uforanderlig per Oslo-dato i eksisterende `runtime_state` med
  nøkkel `bemobi_oslo_reference_v1:YYYY-MM-DD`. Ingen migrering er nødvendig.
- Referansejobben skriver idempotent, uavhengig av NAV-skriverlåsen, slik at en lang
  fulloppdatering ikke blokkerer det korte referansevinduet. Den daglige referansen
  beskyttes atomisk med INSERT ON CONFLICT DO NOTHING; resultat registreres i job_runs.
  Lagrede B3 LAST-kurser med eksplisitt 15-minutters forsinkelse og faktisk
  referansetid innen tre minutter kan gjenopprette en manglende referanse. Dette
  gjøres av 30-minuttersjobben; API-et kan også lese samme grunnlag uten å skrive.
  Kurser utenfor tidsvinduet brukes aldri som referanse.

- Hvis referansen fortsatt mangler etter B3-vinduet, forsøker 30-minuttersjobben
  å gjenopprette den fra eksisterende Yahoo Finance-intradagkilde. Bare siste
  avsluttede ettminuttsstolpe som slutter senest ved Oslo-sluttauksjonen og
  høyst tre minutter tidligere godtas. Stolpen som starter kl. 16:25 brukes
  ikke, fordi den kan inneholde handler etter sluttauksjonen. Symbol, valuta,
  tidssone og dato valideres. Referansen lagres med kilde, stolpestart,
  sluttidspunkt og kildehenvisning, og merkes som omtrentlig i kortet.
  Seneste kurs eller forrige dags sluttkurs erstatter aldri referansen.
  Lagret B3-grunnlag prioriteres, og en frosset referanse overskrives ikke.
  Kilden leverer én dags minuttdata; manglende historikk eller nettverksfeil
  gir fortsatt manglende grunnlag og registreres i recovery-steget.

- På halve handelsdager kan B3 fortsatt være stengt ved close på Oslo Børs. Når ingen
  fersk referanse finnes, vises manglende grunnlag fremfor en oppdiktet kurs.

## Seneste kurs og status

Beregn `(nyeste kurs / referansekurs - 1) * 100`. Bruk bare `LAST`-observasjoner
etter referansen og ikke senere enn faktisk klokke. `CLOSE` med syntetiske
dagstidspunkt brukes ikke. Nyeste kurstid vinner; B3 prioriteres ved lik kurstid,
med Yahoo som eksisterende sekundærkilde. Kurver viser lagrede observasjoner.

Siste gyldige, tidsstemplede kurs etter referansen beholdes frem til neste close
på Oslo Børs, også over natten, før neste B3-åpning og gjennom helger/helligdager.
Alder alene skjuler ikke Bemobi-endring, OTEC-effekt eller teoretisk OTEC-kurs;
faktisk siste kurstidspunkt vises fortsatt. Nye gyldige kurser oppdaterer resultatet.
Fremtidige kurser, ugyldige tall og CLOSE med syntetiske tidspunkt avvises fortsatt.
Nettverksfeil i kortet undertrykker prosentvisningen. Referansen beholdes til neste
close på Oslo Børs.
Når ny sluttauksjon er passert, venter kortet på den nye forsinkede referansen.

Endringen gjelder Cloudflare-produksjonsløsningen. Referanse-backendens lokale API
har ikke dette nye endepunktet eller cron-jobben.

Kilder: eksisterende `cloudflare/src/bmob3_ingestion.py` (B3-forsinkelse),
[Euronexts børsdagskalender](https://www.euronext.com/en/trading/trading-hours-holidays)
og [Oslo migration guidelines](https://connect2.euronext.com/sites/default/files/it-documentation/Oslo_Bors_Migration%20Guidelines%20-%20v2.3.1_0.pdf)
(sluttauksjon og halv dag). Kalenderreglene gjenbruker prosjektets Oslo-kalender.

## Teoretisk OTEC-effekt

`change_per_share_nok = change_brl × Bemobi-beholdning × fast BRL/NOK / utestående OTEC-aksjer`.
`change_pct = change_per_share_nok / OTEC-kurs ved close på Oslo Børs × 100`.

Kortet viser også **Teoretisk OTEC-kurs**: OTEC-kursen ved samme Oslo-slutt pluss
`change_per_share_nok`. Beregningen bruker uavrundede verdier; bare visningen
avrundes til to desimaler. Kursen skjules ved manglende eller foreldet grunnlag,
mislykket oppdatering eller ugyldig resultat. Dette er bare en justering for
Bemobi-bevegelsen med fast valutakurs, ikke en prognose for OTEC-kursen.

Grunnlaget leses for samme Oslo-dato. Sluttkurs for OTEC prioriteres; dersom bare
LAST finnes, brukes siste tidsstemplede handel fra samme handelsdag. Euronext-handler
til og med fem minutter etter sluttauksjonens start (16:30 / 13:10 på halv dag)
godtas, som i eksisterende EOD-ferdigstilling. Andre kilder må være tidsstemplet
senest ved 16:25 / 13:05. Kortet merker LAST-grunnlaget som omtrentlig.
Handler etter auksjonsvinduet brukes ikke. Valutakursen er
siste tilgjengelige dagskurs med eksisterende kildeprioritet (Norges Bank, ECB),
tidsstemplet senest ved close på Oslo Børs og høyst sju dager gammel. Den brukes uendret
på begge Bemobi-kursene. Beholdning og utestående aksjer gjelder Oslo-datoen.

Manglende/ugyldig grunnlag skjuler OTEC-effekten uten å skjule gyldig Bemobi-endring.
Mislykket oppdatering i kortet skjuler begge prosenttallene. Kortene
bruker samme kolonnebredder som NAV/dato-raden og stables på mindre skjermer.
Ingen migrering eller ny ekstern datakilde er nødvendig.


OTEC-grunnlaget inkluderer siste handel fra Euronexts dagsfil (`market_activity`),
med faktisk handelstid innen samme auksjonsvindu. Eksplisitt CLOSE prioriteres på
samme dato i både kursvisning, dagshistorikk og OTEC-effekt. En handel tidligere på
dagen er et merket LAST-grunnlag, ikke en offisiell sluttkurs.

Dagen ferdigstilles fra rullerende filer bare dersom siste handel er ved
sluttauksjonen; ellers kreves hel dagsfil. Gamle ferdigmarkeringer med en tidligere
handel og uten hel dagsfil regnes ikke som tilstrekkelig dekning. Dagsaktivitet
kontrolleres på nytt i to timer etter sluttauksjonen og én gang som forrige
handelsdag for å ta med forsinkede publikasjoner.
Bemobi-referansen og fast valutakurs følger fortsatt 16:25 / 13:05 på halv
handelsdag. Bare OTEC-kursgrunnlaget inkluderer de påfølgende auksjonshandlene.
Dette retter tilfeller der en tidligere handel på 20,05 ble brukt selv om
sluttauksjonens siste handel var 20,00; med effekt −0,01 blir teoretisk kurs
19,99 i stedet for 20,04. Eksisterende lagrede kurser endres ikke.

Kildeprioriteringen kan endre eksisterende kursgrafer og prosentendringer på datoer
hvor både eksplisitt CLOSE og dagsfilens siste handel finnes og er ulike. Lagrede
markedsdata og historiske NAV-beregninger omskrives ikke av denne endringen.

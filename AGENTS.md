# AGENTS.md – OtelloTracker

## Formål

OtelloTracker er et analyse- og overvåkingsverktøy for Otello Corporation (OTEC).

Denne filen beskriver hvordan Codex skal arbeide i prosjektet. Målet er små, kontrollerte og etterprøvbare endringer uten unødvendig påvirkning på eksisterende funksjonalitet.

## Generelle prinsipper

- Bevar eksisterende funksjonalitet med mindre brukeren uttrykkelig ber om noe annet.
- Gjør minst mulig endring som løser oppgaven.
- Følg eksisterende arkitektur, navngiving, komponentstruktur og kodeformat.
- Gjenbruk eksisterende funksjoner, komponenter og biblioteker når det er naturlig.
- Ikke legg til nye avhengigheter dersom eksisterende løsninger kan brukes.
- Ikke gjør større refaktoreringer som ikke er nødvendige for oppgaven.
- Ikke hardkod verdier som naturlig hører hjemme i konfigurasjon eller eksisterende datakilder.
- Ikke slett historiske data, funksjoner eller API-endepunkter uten eksplisitt beskjed.
- Hvis oppgaven er uklar, velg den løsningen som påvirker minst mulig kode og forklar antakelsene.

## Arbeidsmåte

Ved enkle og avgrensede endringer kan Codex gå direkte til implementering.

Ved feilretting, dataproblemer eller større endringer skal Codex først:

1. Finne relevante filer og funksjoner.
2. Kartlegge dataflyten eller årsakssammenhengen.
3. Identifisere sannsynlig rotårsak.
4. Forklare kort hva som bør endres.
5. Implementere løsningen.
6. Kontrollere at eksisterende funksjonalitet fortsatt virker.

Ikke «fikse» symptomer dersom den underliggende årsaken kan identifiseres.

## Git og branches

- Ikke gjør implementasjonsendringer direkte på `main`.
- Før kode endres, kjør `git status`.
- Hvis arbeidsmappen har ulagrede eller ukommitterte endringer før oppgaven starter, stopp og informer brukeren før branch byttes eller opprettes.
- Hvis gjeldende branch er `main`, opprett automatisk en ny branch før kodeendringer starter.
- Bruk korte og beskrivende branchnavn.

Bruk følgende mønster:

- `codex/fix-<kort-beskrivelse>` for feilretting
- `codex/feat-<kort-beskrivelse>` for ny funksjonalitet
- `codex/refactor-<kort-beskrivelse>` for refaktorering
- `codex/chore-<kort-beskrivelse>` for vedlikehold

Eksempler:

- `codex/fix-bemobi-dates`
- `codex/fix-volume-forecast`
- `codex/feat-regulation-page`
- `codex/refactor-market-data`

- Ikke push, merge, rebase eller slett branches uten eksplisitt beskjed.
- Ikke force-push.
- Ikke commit dersom brukeren ber om å se diffen først.

## Data og beregninger

- Behandle markedsdata og selskapsdata som tidsserier der dato, tidspunkt og kilde kan være vesentlig.
- Ikke endre historiske beregninger uten å dokumentere konsekvensen.
- Ved endringer i prognoser eller beregningslogikk skal gammel og ny metode sammenlignes når det er praktisk mulig.
- Unngå å blande ordinært handelsvolum med særskilte transaksjoner dersom kildedataene skiller mellom dem.
- Ved manglende eller uventede data skal løsningen feile kontrollert fremfor å produsere misvisende tall.
- Ikke fyll inn manglende markedsdata med oppdiktede verdier.

## Dato og klokkeslett

- Bruk `Europe/Oslo` for dato og klokkeslett som vises til brukeren, med mindre datakilden eller funksjonen uttrykkelig krever noe annet.
- Vær særlig oppmerksom på UTC-konvertering, sommertid og datoer rundt midnatt.
- Ikke fjern eksplisitt tidssoneinformasjon dersom den er nødvendig for korrekt konvertering.

## Eksterne datakilder

- Bevar eksisterende kildeprioritet og fallback-logikk med mindre oppgaven gjelder dette.
- Ikke endre parsing basert på ett enkelt eksempel uten å kontrollere flere representative eksempler.
- Håndter tomme svar, endret HTML/API-format, timeout og manglende felt kontrollert der dette er relevant.
- Ikke eksponer API-nøkler, tokens eller andre secrets i kode, logger, commits eller testdata.
- Hvis en ekstern kilde er ustabil, dokumenter antakelser og fallback-løsning.

## UI og brukeropplevelse

- Følg eksisterende visuelt uttrykk og komponentmønster.
- Ikke endre layout eller styling uten at det er nødvendig for oppgaven.
- Bevar responsivitet.
- Bruk norsk språk der eksisterende brukergrensesnitt er norsk.
- Unngå å legge til vurderende merkelapper eller unødvendige felter når rådata kan presenteres tydelig direkte.

## Kvalitetssikring

Etter kodeendringer skal Codex, så langt prosjektet støtter det:

1. Kjøre relevante tester.
2. Kjøre lint.
3. Kjøre production build.
4. Kontrollere eventuelle TypeScript-/kompileringsfeil.
5. Oppsummere hvilke filer som er endret.
6. Oppsummere hva som faktisk ble rettet eller lagt til.
7. Opplyse tydelig om tester eller kontroller som ikke kunne kjøres.

Hvis prosjektet har scripts i `package.json`, bruk disse fremfor å finne opp egne kommandoer.

En oppgave skal ikke omtales som ferdig dersom build eller relevante tester feiler på grunn av endringen.

## Sikkerhet

- Ikke legg secrets i repoet.
- Ikke logg tokens, cookies, passord eller API-nøkler.
- Ikke svekk eksisterende autentisering, inputvalidering eller tilgangskontroll uten eksplisitt beskjed.
- Vær forsiktig med kode som henter og gjengir eksternt innhold.
- Varsle brukeren dersom en foreslått løsning har en tydelig sikkerhetsmessig konsekvens.

## Før avslutning

Når oppgaven er ferdig, gi en kort oppsummering med:

- hva som ble endret
- hvilke filer som ble endret
- hvilke tester/kontroller som ble kjørt
- resultatet av disse
- eventuelle kjente begrensninger eller videre arbeid

Hold oppsummeringen kort og konkret.

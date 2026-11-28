# Kildehierarki og reserver – 28.11.2026

Formål: skille aktiv innhenting, uavhengig reserve, kontrollserier og historisk proveniens. Gjennomgangen er basert på produksjonskoden i cloudflare/src og [produksjonsdiagnose 46146073913](https://github.com/MKej88/otello-tracker/actions/runs/46146073913). Den er ikke en ny belastningstest mot eksterne leverandører eller en fullstendig måling av alle nettverkskall.

| Område | Primær / aktiv kilde | Reserve eller tillegg | Vurdering |
| --- | --- | --- | --- |
| BRL/NOK og USD/NOK, daglig historikk | Norges Bank EXR | Historiske ECB-krysskurser | ECB hentes ikke lenger. Behold provenance og historisk fallback; ikke slett kildedata eller kompatibilitetsmodulen uten kontroll av pågående Workflows. |
| BRL/NOK intradag | Exchangerate.dev | Norges Bank som referanse og reserve | Ett kall per ordinær rask oppdatering når aktivert og lisensgodkjent; helger hoppes over. Sammenlignes med Norges Bank før lagring. Oslo-referanse er egen avgrenset oppgave. |
| OTEC intradag og slutt | Euronext | Lengre Euronext-filer ved hull og sluttkontroll | Samme leverandør, ikke uavhengig reserve. Behold deknings- og tidskontroller; eksisterende plan hopper over unødvendig innhenting når EOD er ferdig. |
| BMOB3 intradag | B3 forsinket webkurs | Yahoo Finance for volum og gyldig kursreserve | Yahoo kalles også etter gyldig B3-kurs fordi volum brukes separat. Ikke fjern eller begrens uten å kontrollere volumindikatorer. Samme Yahoo-leverandør har to verter. |
| BMOB3 slutt | B3 COTAHIST for offisiell CLOSE; forsinket B3 webkurs som EOD-LAST | Gyldig sen Yahoo LAST ved svikt i begge B3-banene | LAST er ikke offisiell CLOSE. Behold nattlig offisiell kontroll og arkivering; tidligere EOD-marker alene beviser ikke at COTAHIST er arkivert. |
| Life360 LIF | Yahoo Finance (USD, NASDAQ) | Life360 IR/LSEG ved transportfeil; siste gode data ved svikt | To Yahoo-verter er ikke uavhengige. IR/LSEG er separat reserve. Kontrollserier har egen status og skal ikke automatisk erstatte LIF. |
| Bemobi regulatoriske dokumenter | CVM | Offisiell alternativ URL og verifisert privat R2-original | Siste diagnose viser HTTP 526 for CVM og alternativ URL, men R2 leverte dokument 7538. Behold rekkefølge og verifisering. |
| Bemobi selskapsopplysninger | Bemobi IR, offentlige kilder og CVM | Siste verifiserte eier-/analytiker-/rapportfakta | IR-meldinger og CVM-rapporter dekker ulike behov. Offisielle utdelinger kan ikke erstattes av oversettelsesresultat alene. |
| NewsWeb / Otello | NewsWeb og selskapsrapporter | Verifiserte vedlegg, lagret dokumentgrunnlag og avstemminger | Behold vedleggs- og avstemmingskontroller. |

## Konkrete funn

- `ecb_full_refresh.py` er et kompatibilitetsalias som faktisk kaller Norges Bank. Navnet er historisk, ikke tegn på aktiv ekstern ECB-innhenting. Siste diagnose viser en gammel ECB-status fra 20.08.2026. Rapporten skal derfor merke den som historisk reserve uten å endre lagret status eller alvorlighetsregler.
- `bmob3_ingestion.py`: Yahoo har en separat volumfunksjon i tillegg til kursreserve. To verter er en transportreserve, ikke to uavhengige markedsdatakilder.
- `life360_market_data.py`: uavhengig IR/LSEG-reserve er begrenset til transportfeil. Valideringsfeil er ikke skjult ved automatisk å godta en annen respons.
- `scheduled.py` og `entry.py`: rask og full bane har forskjellige formål. Offisiell daglig kurs, arkivering og kontroll av historikk kan ikke erstattes med siste intradagobservasjon.
- `bemobi_web_refresh_runtime.py`: sekundære resultat-/XP-oppgaver veksler allerede mellom planlagte datoer. Behold pågående oversettelse og dokumentrecovery uendret.

## Videre prioritering

1. Mål antall eksterne kall, HTTP-feil, bruk av fallback og ferskhet per kilde over flere handelsdager. Skill reserve fra volumtillegg og planlagt kontroll.
2. Undersøk om B3 COTAHIST hentes flere ganger for samme dag selv når en offisiell CLOSE med gyldig metadata og R2-original allerede er verifisert. Eventuell deduplisering må bevare korreksjonsmulighet, volumdekning, provenance og arkivering.
3. Vurder færre gjentatte Yahoo-volumkall kun hvis tidsstempler, handelsvolum og Oslo-kort fortsatt tilfredsstiller gjeldende kontrakter.
4. Før eventuell fjerning av kompatibilitetsaliaser eller incident-verktøy: sjekk alle import- og testreferanser og eksisterende Workflow-versjoner.

Ingen kilde fjernes nå. Dette er en konservativ kildeopprydding: dokumentasjon og mer presis diagnostikk, ikke en bekreftet reduksjon i nettverkskall. Kildeprioritet, datoferskhet og historiske data holdes uendret.

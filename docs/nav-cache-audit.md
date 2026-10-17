# NAV-avstemming og kontroll av mellomlagrede data

Utvider den eksisterende daglige read-only diagnosen med tre SELECT-spørringer
og én offentlig GET av `/api/dashboard/bootstrap`. Bruker dagens lesetoken uten
nye rettigheter. Skriver ikke til produksjonsdata eller cache.

## NAV

- Henter nyeste FULL og tilhørende CORE for samme dato og gjeldende
  beregningsversjoner. Kontrollerer total NAV / utestående aksjer, summering av
  Bemobi + cash + andre netto eiendeler og NAV-rabatt.
- Slår opp COREs opprinnelige kurs-, valuta-, beholdnings-, aksjeantalls- og
  cash-rader. Kontrollerer Bemobi-aksjer × kurs × BRL/NOK, OTEC-kurs og cash,
  samt at nyeste gyldige beholdning/aksjeantall og tilgjengelige datadatoer brukes.
- Avstemmer FULLs andre netto eiendeler mot dagsestimatet.
- Sammenligner NAV og aksjeantall i lagret cache og nettsidens offentlige svar
  med FULL i D1. Regnskaps-NAV og investor-NAV behandles som ulike modeller.
- Investor-NAV kontrolleres gjennom total/per aksje, summen av komposisjonen og
  en selvstendig beregning av kontant opsjonsoppgjør. Regnskapsmessig FULL NAV og
  opsjonsgrunnlag hentes fra D1; publiserte cash-FX-, Life360- og driftsjusteringer
  brukes som scenarioforutsetninger. Life360 aksjer × kurs × USD/NOK kontrolleres.
- Begge NAV-rabattene på nettsiden kontrolleres mot vist OTEC-kurs.

Dette kontrollerer beregninger og konsistens, ikke om verdsettelsesforutsetninger
eller rapporterte beholdninger er riktige hos selskapet. Eksisterende kontroller
av kildeferskhet beholdes. Beløpstoleransen er 1 NOK, per aksje 0,000001 NOK og
rabatt 0,0001 prosentpoeng, slik at JSON-flyttall ikke gir avrundingsvarsler.

## Cache og nettside

Cache-nøkkel, versjon, seksjoner og maksimal alder leses fra de faktiske
produksjonskonstantene uten å importere Worker-/FastAPI-runtime. Gjeldende
maksimalalder er derfor den samme som på siden, ikke en separat hardkodet grense.

Diagnosen kontrollerer lagret versjon/struktur/alder, at cache er bygget etter
siste NAV-endring, og at den offentlige siden bruker samme generasjon og tall.
HTTP-proben bruker unik query-parameter og Cache-Control: no-cache. HTTP-feil,
ugyldig JSON eller live fallback registreres som avvik.

Kryssammenligninger kan stå AVVENTER mens en aktiv skrivelås har ferskt heartbeat,
eller i 120 sekunder etter en NAV-/cacheendring som overlapper proben. Intern
aritmetikk, ugyldig versjon/struktur og for gamle data får ingen utsettelse.
Avventende kontroller bekrefter ikke at dataene allerede er avstemt.

Resultatet inngår i samme GitHub Actions-avviksvarsling som den øvrige diagnosen.
En endring i kontrollmodulen utløser også en produksjonsdiagnose på main.

## Tester

Regresjonstester dekker aritmetiske feil, endrede grunnlagsrader, gamle cache- og
HTTP-svar, feil versjon, manglende seksjoner, samtidig oppdatering, opsjonsoppgjør,
Life360 og ugyldige/ikke-endelige tall. SQL kjøres mot skrivebeskyttet SQLite og
hele diagnosejobbens Python-blokker testes med alle tolv resultater.

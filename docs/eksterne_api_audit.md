# Revisjon av eksterne API-kall

Dato: 30. august 2026  
Omfang: produksjonskode i `backend/app` og `cloudflare/src` som gjør HTTP-kall.

## Hvordan revisjonen ble gjort

Alle Python-kall via `urllib.request.urlopen` og Workers `fetch` ble søkt opp. For
hver integrasjon ble nedlasting, validering, lagring og eventuell fallback vurdert
samlet. Et funn regnes bare som en feil når et konkret svar kan føre til feil data,
ukontrollert feil eller unødvendig arbeid. Den eneste kodeendringen nedenfor ble
først gjenskapt med en test som feilet.

## Bekreftet og rettet funn

### BCB SGS kunne vise en eldre observasjon som den nyeste

`_series_payload` bruker siste rad som gjeldende verdi. `_parse_sgs_rows` beholdt
rekkefølgen fra leverandøren, selv om HTTP-kontrakten ikke garanteres lokalt og
koden ikke sender et sorteringsvalg. En gyldig, men omvendt/delvis sammensatt
respons med 28. august før 27. august førte derfor til at 27. august ble vist som
nyest. Dette er et realistisk scenario ved endret responsrekkefølge og kunne
presentere stale data som ferske.

En reproduksjonstest med to omvendt sorterte observasjoner feilet med dato
`2026-08-27` i stedet for `2026-08-28`. Parseren sorterer nå validerte rader på
ISO-dato. Samtidig avvises ugyldige datoer kontrollert; tidligere kunne enkelte
tekstverdier passere videre og bli sammenlignet/levert som dato.

Vurdering før retting:

1. Situasjonen ble **ikke håndtert korrekt**.
2. Kallet feilet **ikke kontrollert**, fordi responsen var syntaktisk gyldig.
3. Koden kunne **presentere stale data som siste verdi**.
4. Koden kunne ikke bli stående fast; det finnes ingen retry-loop her.

## Resultat per integrasjon

| Integrasjon | Scenarier og dagens oppførsel | Vurdering |
|---|---|---|
| BCB SGS (Brasil-dashboard) | Timeout/429/5xx bobler opp og dashboardets overordnede samling kan bruke cache/fallback. Tom respons, feil toppnivå, manglende verdi og ugyldig tall avvises. Rekkefølgefeilen er rettet. Ingen paginering er nødvendig fordi dato-vinduet er avgrenset. | Kontrollert etter retting. |
| BCB Focus/OData | HTTP-feil og ugyldig JSON feiler kontrollert. Manglende `value` avvises i hovedparseren; enkelte valgfrie forventningsendepunkter gir tom liste og dermed ingen berikelse. `$top=1200` har ingen oppfølging av OData-`nextLink`; de korte, filtrerte vinduene gjør dette foreløpig til en risiko, ikke en bekreftet feil. | Ingen endring. Overvåk radantall/`nextLink` hvis vinduene utvides. |
| B3 BMOB3 web quote (backend/Worker) | Størrelse, JSON-form, statusfelt, symbol, pris og leverandørtid valideres. Backend har tre avgrensede forsøk; Worker går til en separat Yahoo-fallback. Gamle leverandørtider kontrolleres før lagring. | Håndtert. Backend retryer også permanente 4xx, men maksimalt tre ganger; lite, avgrenset merarbeid. |
| Yahoo Finance BMOB3 fallback | Begge vertsnavn prøves én gang, responsstørrelse og nødvendige chart-felt valideres, og data merkes som uoffisiell fallback. | Håndtert; ingen uendelig retry. |
| B3 COTAHIST | Dag-/årsarkiv har timeout, størrelsesgrense, ZIP-/radvalidering og avgrensede retries. Importen er idempotent. Tomt/ufullstendig arkiv feiler før markedstall lagres. | Håndtert. |
| Euronext delayed trades | Tom fil, for stor fil, ugyldig ZIP/CSV, manglende felt, datatyper, valuta, venue og tidsstempler valideres. 429 og 5xx bruker maksimalt tre forsøk og `Retry-After` avgrenses til 60 sekunder. Duplikater håndteres av identitet/upsert. | Håndtert. Ingen pagination i filendepunktet. |
| Norges Bank SDMX FX | Timeout/HTTP/JSON-feil bobler kontrollert til jobbsteget. Struktur, dimensjoner, datatype, positive kurser og at alle tre valutaer finnes valideres før import. En delvis respons lagres derfor ikke som komplett kjøring. | Håndtert. Ingen eksplisitt retry, så en kortvarig 429/5xx gir én kontrollert mislykket oppdatering og eksisterende data beholdes. |
| ECB CSV FX | CSV-header, dato, datatype og positive kurser valideres. Tom gyldig CSV kan gi null rader, men brukes kun i eksplisitt bootstrap/backfill og gir ikke falske kurser. HTTP-feil har ingen retry. | Kontrollert, men operatøren må gjenta bootstrap/backfill ved midlertidig feil. |
| CVM IPE årsarkiv og dokumenter | Årsarkiv har timeout, størrelse, tomrespons, skjema og tre avgrensede forsøk. Dokumentlenker og innhold valideres før finansielle fakta opprettes; nyeste versjon markeres og supersederte dokumenter kan filtreres. | Håndtert. 404 retries også, men bare tre ganger. |
| Bemobi IR/CVM/analytikersider | Worker har avgrenset responslesing, tillatte domener, dokumenttypekontroll og streng parsing før lagring. Kandidatlenker dedupliseres og begrenses. Ugyldige/ufullstendige kilder blir kildefeil, ikke finansielle fakta. | Håndtert; ingen uendelig retry/paginering. |
| NewsWeb liste, melding og vedlegg | Statusheader, responsstørrelse, JSON-struktur, utsteder, marked, ID og PDF-signatur valideres. `overflow` håndteres ved å dele datointervallet rekursivt; overflow på én dato stopper kontrollert. Databaseidentitet hindrer duplikater. | Håndtert. Timeout/429/5xx retries ikke lokalt, men jobbfeilen er kontrollert og gamle data overskrives ikke. |
| MFN/Euronext buyback-speil (backend) | Timeout/HTTP-feil bobler for listesiden; enkeltartikler isoleres som feil. Streng kilde- og finansparser kjøres før lagring, og database/import er idempotent. En gyldig, men tom/ufullstendig listeside kan gi null funn; etterfølgende dekningskontroll flagger hull, og kjent offisiell backfill kjøres. | Feiler kontrollert via dekningsstatus; kan beholde gamle data, men merker dem ikke som komplett når det finnes dato-hull. |
| Euronext intradag/recovery i Worker | HTTP-status, størrelse og filformat valideres. Recovery bruker avgrensede perioder; oppslag dedupliseres ved lagring. | Håndtert. Midlertidige feil gir kontrollert jobbfeil fremfor lokal retry-loop. |
| Life360 IR/LSEG og markedsdata | Responsstatus, størrelsesgrenser, identitet, dato og numeriske felt valideres. Proveniens og alder følger verdien, og eksisterende kuraterte data beholdes når ekstern oppdatering feiler. | Håndtert; fallback kan være stale, men er merket med dato/kvalitet. |

## Tverrgående konklusjon

Det finnes ingen ubegrensede retry-looper i de gjennomgåtte kallene. Retry finnes
bare i noen nedlastere og er begrenset til tre forsøk. Rate-limit-respons håndteres
mest presist i Euronext-kallet; de øvrige kallene stopper eller faller tilbake og
kan derfor miste én oppdatering, men de spinner ikke og lagrer ikke HTTP-feilsvar
som markedsdata. Deduplisering skjer hovedsakelig ved dokumentidentitet, hash eller
database-upsert. Den eneste bekreftede veien til feil presentasjon var SGS-
rekkefølgen, som nå er testet og rettet.

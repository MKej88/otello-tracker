# Ytelsesanalyse av markedskurser (2026-09-26)

## Hvorfor dette er en viktig kjørebane

`market_quote_details` bygger kursdelen av dashboardets første skjerm. Den brukes både
i det samlede bootstrap-svaret og i `/api/market/quotes`. For hvert av de tre
instrumentene hentes siste kurs først. Deretter ble tre uavhengige lesinger kjørt etter
hverandre: ett års kurshistorikk, forrige sluttkurs og dagens handelsstatistikk. OTEC har
i tillegg en volumlesing som må vente på historikken.

Dette er nettverkskall til Cloudflare D1, ikke små beregninger i minnet. Query-antallet
endres ikke, men unødvendig seriell venting gjør responstiden til summen av flere
nettverksrunder.

## Måling før endringen

En deterministisk reproduksjon erstattet hver databaselesing med 30 ms ventetid og
kjørte OTEC-kjeden sju ganger. Medianen var **181,2 ms** (målingene lå mellom 180,9 og
181,4 ms). Det tilsvarer seks serielle ventebølger.

## Kandidater og prioritering

| Kandidat | Forventet effekt | Confidence | Risiko | Rangering |
| --- | --- | --- | --- | --- |
| Kjør uavhengig historikk, sluttkurs og sesjonsdata parallelt | Høy: tre D1-runder blir én på en synlig kjørebane | Høy | Lav | 1 – implementert |
| Batch alle kurs-spørringer på tvers av instrumenter | Potensielt høyere | Middels | Høy: stor SQL- og grupperingsendring | 2 – ikke valgt |
| Mellomlagre hele kurssvaret i Worker-minnet | Middels | Lav | Middels: kan gi foreldede data mellom isolater | 3 – ikke valgt |

Rangeringen bruker forventet effekt × confidence ÷ implementasjonsrisiko. Den valgte
endringen er liten og endrer verken antall spørringer eller datagrunnlag.

## Måling etter endringen

Samme reproduksjon ga en median på **120,9 ms** (målingene lå mellom 120,8 og
121,0 ms). Det er omtrent **33 % kortere ventetid** i den simulerte OTEC-kjeden, fra
seks til fire ventebølger. Reell gevinst varierer med D1-latens og cachetreff.

## Korrekthet, feil og trade-off

Historikk, forrige sluttkurs og sesjonsdata bruker bare resultatet fra den allerede
avsluttede siste-kurs-lesingen; de avhenger ikke av hverandre. Volumberegningen venter
fortsatt på historikken. Eksisterende responsformat og beregninger er uendret.

En test verifiserer at de tre lesingene faktisk starter samtidig, og en egen test
verifiserer at databasefeil fortsatt sendes videre i stedet for å bli skjult. Trade-offen
er at opptil tre D1-lesinger nå kan være aktive samtidig for ett instrument. Det gir
kortere ventetid uten flere spørringer, men litt høyere momentan parallellitet.

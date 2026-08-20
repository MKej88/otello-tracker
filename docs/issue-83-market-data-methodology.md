# Issue #83 – metode for utvidede kursdata

Denne endringen legger til kurs- og handelsdata for OTEC og BMOB3 i investoroversikten.

## Felt

Begge instrumentene viser:

- sist oppdatert
- 52-ukers lav/høy
- snittvolum (inntil 20 siste tilgjengelige fullførte handelssesjoner)
- siste tilgjengelige fullførte dagsvolum
- åpning
- dagens lav/høy
- siste sluttkurs

## BMOB3

Dagens åpning/lav/høy kommer fra B3s forsinkede offentlige webkurs når den er tilgjengelig. Etter fullført handel lagrer den daglige COTAHIST-innhentingen PREABE, PREMAX, PREMIN, PREMED, PREULT, TOTNEG, QUATOT og VOLTOT. QUATOT brukes som aksjevolum; VOLTOT er finansiell omsetningsverdi og brukes ikke som aksjevolum.

## OTEC

Fullført dagsvolum kommer fra Euronext-basert `market_activity`. Dagens åpning/lav/høy beregnes fra direkte Euronext LAST-handler som trackeren faktisk har lagret. Dette merkes `OBSERVED_TRADES` i API-et og skal ikke omtales som en komplett offisiell OHLC-sesjon.

## 52 uker

Historisk intervalldata bruker lagret dags høy/lav når det finnes. For eldre dager hvor kun verifisert sluttkurs finnes, brukes sluttkurs som fallback. API-et returnerer metodegrunnlaget eksplisitt.

## Kvalitetsprinsipp

Manglende datapunkter vises som manglende. Det estimeres ikke åpning, dagsvolum eller offisiell dags høy/lav fra svake tredjepartskilder.

# CVM capex: tidlig filtrering på selskap

## Problem og viktig kjørevei

Produksjonens `entry.py:cvm_step` kaller `refresh_bemobi_cvm`, som kaller
`refresh_bemobi_reported_net_income` → `_parse_year_financials` →
`parse_capex_accounts_archive`. Regnskapsoppdateringen kjøres normalt ukentlig
fra nattjobben, med kortere intervall ved manglende kvartalstall. Ved behov
behandles både inneværende års ITR og foregående års ITR/DFP.

Capex-parseren analyserte `DS_CONTA` for hele markedet: Unicode-normalisering,
fjerning av diakritiske tegn og tekstmatching. Først etterpå avviste
`_row_to_observation` selskaper utenom Bemobi. Nå brukes samme selskapsfilter
før tekstanalysen. Dette er den eneste produksjonsendringen.

Kandidatvurdering før endringen, skala 1–5: forventet effekt 3 × confidence 5
÷ implementasjonsrisiko 1 = **15**. Arbeidet skalerer med hele markedsarkivet,
mens endringen bare flytter et allerede eksisterende, rent filter tidligere.

## Reproduksjon og resultater

Kjør `python tools/benchmark_cvm_capex.py` fra repoet, uten ekstra avhengigheter.
Bruk samme skript mot før- og etterversjonen av produksjonsmodulen.

Deterministisk, syntetisk ITR-arkiv: 400 selskaper, tre kvartaler, 100 kontorader
per selskap/kvartal; 120 000 rader i hver av DRE, DFC, BPA og BPP. Ett selskap
er Bemobi. ZIP-generering og instrumentering inngår ikke i tidtakingen.
Målingene er median av fem kjøringer på lokal CPython 3.12.14.

| Måling | Før | Etter | Reduksjon |
| --- | ---: | ---: | ---: |
| Kall til `_is_capex_label` | 120 060 | 360 | 99,7 % |
| Hele capex-parseren | 685,4 ms | 263,2 ms | 61,6 % |
| Hele `_parse_year_financials` | 1 659,8 ms | 1 258,2 ms | 24,2 % |

Før/etter SHA-256 av resultatene var identiske:

- Capex: `df582bc9911a950b2c1461530abdd4713bd2406793f6b3b1f0502d69bfd38add`
- Årsparser: `7cb45fb4562921227371549541a2d3e17f50aaeda59290e28bf50dd6e5f9bf23`

Dette dokumenterer lokal CPU-kostnad for et syntetisk markedsarkiv, ikke faktisk
produksjonsvolum, Worker-timing eller varigheten av hele nattjobben.

## Korrekthet, feil og trade-off

79 sammenligninger mot gammel parser ga identiske resultater eller identiske
feiltyper og feilmeldinger. Scenariene omfattet selskapskoder med innledende
nuller/mellomrom, andre selskaper, tomme/ugyldige verdier, ulike kontotekster,
versjoner, motstridende tall og ugyldige/mangelfulle ZIP-arkiver.

Tolv relevante testfunksjoner fra `test_bemobi_cvm_financials.py`,
`test_bemobi_cvm_standardized_dre.py` og `test_bemobi_cvm_balance_cashflow.py`
bestod ved direkte kjøring. To regresjonstester dekker unngått tekstanalyse av
andre selskaper og fortsatt avvisning av feil i Bemobi-data. Python-kompilering
og `git diff --check` bestod. Pytest, Ruff og Worker-produksjonsbygg ble ikke
kjørt: verktøyene manglet, og nettverkstilgang for installasjonen ble blokkert
av automatisk godkjenningskontroll med melding om nådd bruksgrense.

Alle CSV-rader leses fortsatt. Nettverk, databasekall, minnekompleksitet,
kildeprioritet, finansielle beregninger og oppdateringsintervall er uendret.
Bemobi-rader får én ekstra kontroll av selskapskode; gevinsten avhenger av
antall andre selskaper i arkivet. Ingen cache, ekstra samtidighet eller nye
avhengigheter er innført.

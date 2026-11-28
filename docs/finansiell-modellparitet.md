# Finansiell modellparitet – 28.11.2026

Referansebackend (SQLite) og produksjon (Cloudflare/D1) beholdes som separate implementasjoner. Felles filnavn alene er ikke bevis på semantisk duplisering. Kartleggingen fant 27 par Python-filer med samme filnavn (ekskludert __init__.py), hvorav historisk investeringsattribusjon har identisk Git-blob. Andre forskjeller kan skyldes synkron/asynkron I/O, SQL og dokumentasjon.

| Område | Eksisterende bevis | Utvidelse / restarbeid |
| --- | --- | --- |
| Dashboard og tilbakekjøpsprognose | test_cloudflare_worker_parity.py sammenligner resultatene mot samme SQLite-fixture | Behold uavhengig implementasjon; utvid senere med flere markedsregimer og manglende data. |
| Opsjonsoppgjør | test_option_nav_settlement.py sammenligner oppgjør og waterfall | Ny matrise med null opsjoner, rundt strike, negativ og høy NAV, flere aksjeantall samt ugyldige inndata. Kontroller også uavhengige kontantidentiteter. |
| Kontantbro | build_cash_bridge i begge economic_nav.py har samme matematiske logikk og toleranse ved gjennomgang | Ny matrise med utbetalinger, tilbakekjøp, drift, valuta, patent og små bevegelser. Avstem synlige bevegelser og kontant per aksje. |
| NAV-attribusjon | _build_change_attribution i begge estimated_nav_history.py har samme formel og utdata ved gjennomgang | Ny matrise med aksjeantall, manglende kursattribusjon, JCP-omklassifisering og avstemming. August-kontrollen av betaling utvides til begge runtime-implementasjoner. |
| Kontantvaluta | _cash_fx_revaluation bruker tilsvarende beregning, men synkron og parallell asynkron datalesing | Videre test: samme kildedata for USD, BRL, NOK og uallokert saldo, manglende eller uavstemte grunnlag. |
| Live NAV / historikk | Live composition gjenbruker dagsberegning og kontantsplitt i hver runtime; eksisterende kontrakttester | Full verdi- og datoferskhetsparitet på felles databasefixture gjenstår. |
| Black-Scholes / regnskapsført opsjon | Egen option_liability i begge | Behold skille mot hypotetisk økonomisk kontantoppgjør. Gjennomgå datatilgang, parametere og edge cases separat. |

## Kontrollprinsipp

Test samme inndata mot begge implementasjoner og uavhengige matematiske identiteter. Likhet mellom to modeller er ikke alene bevis for korrekt finansmodell. Testene gjelder syntetiske scenarier, ikke faktiske nye produksjonsverdier. Ingen beregningsfunksjoner, tabeller eller finansielle forutsetninger endres i denne fasen.

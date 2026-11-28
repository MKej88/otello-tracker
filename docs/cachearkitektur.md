# Cachearkitektur – 28.11.2026

D1 er autoritativ for lagrede finansielle grunnlagsdata. De ulike cachelagene har ulike formål; like navn eller payloads er ikke alene grunnlag for å slå dem sammen.

| Lag | Nøkkel / eier | Ferskhet og fallback |
| --- | --- | --- |
| Dashboard hot snapshot | runtime_state dashboard_hot_snapshot_v12; dashboard_hot_snapshot.py | Maks 90 min. Samler summary, economic, quotes, buyback og events. Ved manglende/ugyldig/utløpt snapshot brukes liveberegning. |
| Investor-snapshots | investor_bemobi_dashboard_snapshot_v1, investor_bemobi_consensus_snapshot_v1, investor_buybacks_dashboard_snapshot_v1 | Maks 40 min og samme Oslo-dato. Ikke historiske as-of-kall. Behold forrige gyldige snapshot ved delvis feil; etter utløp liveberegning. |
| Materialisert NAV-historikk | estimated_nav_history_points og materialized_discount_period; seks standardperioder | Versjon, siste historikkdato og eksplisitt ugyldiggjøring ved historisk rettelse; historikkpunkt og cacheinvalidering i samme transaksjon. Ved manglende periode-cache liveberegning. |
| HTTP-levering | app.py CACHE_POLICIES | Se tabell nedenfor. Cache av HTTP-respons, ikke en ny finansberegning. |
| Navigasjonscache | navigationDataPreload.ts, URL og pågående forespørsel | 30 sekunder; gjenbruk av prefetch og samtidige forespørsler. NAV-perioder samles etter første synlige periode. |
| Nettleserens sist-gode bootstrap | localStorage otello.dashboard.bootstrap.v3 | Maks 7 dager etter lagring; rask førstevisning med umiddelbar nettverksrevalidering, deretter egne endepunkt/polling. Dette er IKKE en påstand om datoferskhet. |
| Kort sist-god cache | shortLivedResourceCache.ts, minne/sessionStorage | FX 120 sek, runtime-status 10 sek. Begrenset til allowlist. Ikke ekstra cache av NAV eller aksjekurs. |

## HTTP-grenser i produksjonskoden

Sekunder; browser / edge / stale-while-revalidate på edge. Faktisk HIT og Age avhenger av Cloudflare-konfigurasjon og respons. Grensene er ikke en garanti for samlet datoferskhet; en cached respons kan allerede inneholde et eldre snapshot.

| Endepunkt | Browser | Edge | SWR |
| --- | ---: | ---: | ---: |
| bootstrap, summary, economic, waterfall | 15 | 60 | 120 |
| market/quotes | 30 | 300 | 1800 |
| market/bemobi-after-oslo | 15 | 15 | 0 |
| fx/dashboard | 30 | 120 | 180 |
| dashboard/runtime-status | 15 | 30 | 60 |
| buybacks/dashboard og overview-status, bemobi/dashboard | 60 | 300 | 600 |
| dashboard/history, discount-history, nav-periods, bemobi/consensus, brazil/dashboard | 300 | 1800 | 3600 |

## Konkret rettelse

Dashboardets leser kontrollerte tidligere bare at de fem seksjonsnøklene eksisterte. Diagnostikken krevde derimot at hver seksjon var et JSON-objekt. Et ugyldig snapshot kunne dermed bli akseptert for serving, men avvist av statuskontrollen. En bootstrap med f.eks. null eller liste i quotes kunne dessuten feile under normalisering.

Samlet struktur- og eksakt aldersvalidering brukes nå av begge baner. Ved ugyldig seksjon forkastes snapshot for både enkeltdel, flerdel og bootstrap. Status gir MISS, og bootstrap bruker eksisterende live fallback uten å skrive fra HTTP. Subsekundalder vurderes før eventuell avrunding av visningsfelt. Versjon, nøkkel, TTL og finansielle modeller beholdes. Ikke krev ready=true for alle seksjoner: gyldig API-objekt med ready=false kan uttrykke legitim mangel på data.

## Gjenværende kontroll

- Undersøk om HTTP-cache for markedsdata og NAV kan gi ulike generasjoner på tvers av sider. Mål respons-Age og faktisk datadato før TTL-endring. Oppdateringsfrekvens er ikke samme som maksimal datalder.
- Test nettleserens sist-gode bootstrap ved fremtidig lagringstid, langvarig åpen fane, utløp og overlappende revalidering. Begrens endringer til førstevisning; bevar eksisterende preload-gevinster.
- Behold avstemming i nav-cache-audit.md og eksisterende atomisk invalidasjon for materialisert historikk. Ikke del cache mellom regnskaps-NAV og investor-NAV.
- Dokumenter eventuelle konkrete inkonsistenser med tidspunkt og generasjon før ytterligere inngrep.

Ingen cache-TTL, kildeprioritet, regneverdier, D1-skjema eller oversettelsesprosess er endret i denne fasen.

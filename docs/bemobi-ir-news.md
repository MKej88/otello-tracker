# Bemobi: direkte IR-meldinger og kildealder

Nyhetsvisningen supplerer CVM IPE med Bemobis offisielle MZ-dokumentfeed.
Kilden er oppgitt av selskapets dokumentliste:
https://ri.bemobi.com.br/en/financial-information/documents-filed-at-cvm/

POST-endepunkt, selskap-ID, kategorier og språk er kontrollert mot sidens
`fmId`, `fmBase`, `configPage` og `mziq.cmsint.js` 17.10.2026.
Markedsmeldinger, meldinger til aksjonærer og vesentlige meldinger hentes hver
natt i eksisterende CVM-steg, uavhengig av hvor oppdatert CVMs samlefil er.
I januar undersøkes også foregående år. Ingen nye cron-jobber eller
uautoriserte tredjepartskilder brukes.

Snapshot lagres i runtime_state/bemobi_official_news_v1. Vellykket tomt svar
fjerner gamle IR-oppføringer; nettverks-/formatfeil beholder siste gode sett.
Lenker valideres mot Bemobis selskap-ID og offisielle MZ-verter. Fremtidige,
upubliserte og andre selskapers dokumenter publiseres ikke. API-kontroll som
er mer enn én dag gammel varsles i nyhetsvisningen.

Før første nattjobb vises én kildeverifisert startobservasjon: meldingen
14.10.2026 om salg av vesentlig aksjepost. Den finnes i API-svaret kontrollert
17.10.2026 med ID 60ff8d82-c729-4c37-8b3a-2be854f0d79f. Startobservasjonen
brukes aldri før observasjonsdatoen eller over et vellykket live-snapshot.
Den er metadata, ikke en analyse av dokumentets innhold. Den vises med
original PDF-lenke og uten automatisk NAV-/kontanteffekt.

Eksisterende CVM-oppføringer har prioritet ved en entydig tittel-/dato-match
på tvers av kildene. De ulike navnene for meldinger om vesentlige aksjeposter
normaliseres. Flere meldinger av samme type på én dag slås ikke sammen
automatisk; de kan gjelde forskjellige investorer. Eksisterende CVM-
versjons-/innholdsduplisering er uendret.

CVM-filens Last-Modified lagres separat fra kontrolltidspunktet i
runtime_state/cvm_ipe_archive_freshness. Over tre dager gammel kildefil gir
partial/degradert CVM-status og et konkret datert varsel i nyhetsvisningen.
En vellykket HTTP-nedlasting alene dokumenterer ikke at dataene er ferske.
Manglende Last-Modified gir også et synlig avvik i produksjonsinnhentingen.
Ingen nye Bemobi-meldinger er i seg selv ikke et tegn på utdatert kildefil.

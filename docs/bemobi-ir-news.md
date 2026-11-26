# Bemobi: direkte IR-meldinger og kildealder

Nyhetsvisningen prioriterer Bemobis offisielle MZ-dokumentfeed for selskapets
meldinger. Offisielle resultatrapporter oppdages nå gjennom CVM RAD, med
verifisert privat R2-speiling som primær transport og direkte CVM som reserve.
CVM IPE er en kompletterende kilde for øvrige dokumenter;
CVMs strukturerte ITR/DFP-arkiver brukes fortsatt til regnskapstall og CAPEX.
Kilden er oppgitt av selskapets dokumentliste:
https://ri.bemobi.com.br/en/financial-information/documents-filed-at-cvm/

POST-endepunkt, selskap-ID, kategorier og språk er kontrollert mot sidens
`fmId`, `fmBase`, `configPage` og `mziq.cmsint.js` 17.10.2026.
Markedsmeldinger, meldinger til aksjonærer og vesentlige meldinger hentes hver
natt i eksisterende CVM-steg, uavhengig av hvor oppdatert CVMs samlefil er.
Den uavhengige kategorifiltrerte IR-forespørselen er obligatorisk.
De fire valgfrie MZiQ-rapportprobene er avviklet (status `retired`, ikke `ok`).
Tidligere validerte rapportlenker beholdes. CVM-speilingen kontrollerer den
nyeste offisielle resultatrapportens identitet, kvartal og dokumenthash, også
for fremtidige kvartaler. Ubekreftet CVM-rapportdekning gir fortsatt PARTIAL.
Andre dokumenttyper, som presentasjoner og kvartalsregnskap, kan fremdeles
komme gjennom CVM IPE-arkivet; samme-dagsdekning for disse er ikke garantert.
I januar undersøkes også foregående år. Ingen nye cron-jobber eller
uautoriserte tredjepartskilder brukes.

Snapshot lagres i runtime_state/bemobi_official_news_v1. Vellykket tomt svar
erstatter gamle meldinger, men beholder tidligere validerte rapportdokumenter; nettverks-/formatfeil beholder siste gode sett.
Lenker valideres mot Bemobis selskap-ID og offisielle MZ-verter. Fremtidige,
upubliserte og andre selskapers dokumenter publiseres ikke. API-kontroll som
er mer enn én dag gammel varsles i nyhetsvisningen.

Før første nattjobb vises én kildeverifisert startobservasjon: meldingen
14.10.2026 om salg av vesentlig aksjepost. Den finnes i API-svaret kontrollert
17.10.2026 med ID 60ff8d82-c729-4c37-8b3a-2be854f0d79f. Startobservasjonen
brukes aldri før observasjonsdatoen eller over et vellykket live-snapshot.
Den er metadata, ikke en analyse av dokumentets innhold. Den vises med
original PDF-lenke og uten automatisk NAV-/kontanteffekt.

Bemobi IR har prioritet ved en entydig tittel-/dato-match
på tvers av kildene. CVM brukes når tilsvarende dokument ikke foreligger hos IR. De ulike navnene for meldinger om vesentlige aksjeposter
normaliseres. Flere meldinger av samme type på én dag slås ikke sammen
automatisk; de kan gjelde forskjellige investorer. Eksisterende CVM-
versjons-/innholdsduplisering er uendret.

CVM-filens Last-Modified lagres separat fra kontrolltidspunktet i
runtime_state/cvm_ipe_archive_freshness. CVM IPE oppdateres ukentlig av CVM; derfor tolereres opptil ti kalenderdager
(syv dager + tre dagers margin) siden Last-Modified før PARTIAL/DEGRADED.
Dette er kildeferskhet, ikke en garanti for at CVM har publisert alle
meldinger ennå. IR er den primære meldingskilden.
En vellykket HTTP-nedlasting alene dokumenterer ikke at dataene er ferske.
Manglende Last-Modified gir også et synlig avvik i produksjonsinnhentingen.
Ingen nye Bemobi-meldinger er i seg selv ikke et tegn på utdatert kildefil.

Kilde for oppdateringsfrekvens: https://dados.cvm.gov.br/dataset/cia_aberta-doc-ipe

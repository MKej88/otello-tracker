# Bemobi Q3 2026: offentlige forhåndsestimater

BTG publiserte «Telecom & Tech – Prévia 3T26 (II)» 08.10.2026:
https://content.btgpactual.com/research/home/relatorio/6ac79ea65a2606707e77d83d/Telecom-Tech-Previa-3T26-II

Bemobi-avsnittet oppgir omsetningsvekst 28 % år/år, EBITDA-vekst 36 % år/år,
EBITDA-margin 35,7 % og cash profit R$ 48 millioner. Migreringene lagrer de
eksplisitte tekstverdiene. Absolutt omsetning og EBITDA er ikke beregnet fra
vekstratene, og cash profit er ikke ommerket til justert nettoresultat.

Tidligere sjekket den aktive innhentingen bare XP og bare annenhver natt.
XP-lenkene måtte dessuten inneholde BMOB3; sektorrapporter kunne derfor bli
oversett. Q3-kontrollen undersøker nå XP og BTG hver natt i eksisterende
FullRefreshWorkflow. Den stopper når RESULT/3Q26 finnes eller neste kvartal
er rullet videre av resultatinnhentingen. Ordinær sekundærrotasjon fortsetter
for øvrige kvartaler; ingen nye cron-triggere er lagt til.

XP og BTG beholdes som separate estimatsett i NEXT_QUARTER/3Q26. Eldre
publikasjoner og framtidsdaterte estimater erstatter ikke siste bekreftede
sett. Rapportdato og estimater fra andre meglerhus bevares. Oppdagelse krever
ikke Bemobi i tittelen, men parsingen krever et eget Bemobi-avsnitt i
sektorrapporter, slik at tall fra andre selskaper ikke blir brukt.

BTGs forside eksponerte ingen rapportlenker i HTML ved kontroll 10.10.2026.
Den kjente rapporten kontrolleres derfor også direkte. Manglende oppdagelse
av nye lenker rapporteres som best-effort-advarsel, også når den kjente
rapporten kan leses. Dette er ikke en fullstendig BTG-katalog; et supplerende
nettsøk er nødvendig for nye rapporter som ikke eksponeres i HTML.
Bildetabeller blir ikke automatisk OCR-behandlet av Worker-parseren.

Produksjon følger eksisterende PR → CI → merge → produksjons-CI → deploy,
inkludert D1-migreringen før Worker/asset-deploy. Se `ci-auto-deploy.md`.

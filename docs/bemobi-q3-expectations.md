# Bemobi Q3 2026: offentlige forhåndsestimater

BTG publiserte «Telecom & Tech – Prévia 3T26 (II)» 08.10.2026:
https://content.btgpactual.com/research/home/relatorio/6ac79ea65a2606707e77d83d/Telecom-Tech-Previa-3T26-II

Vedlagt original-PDF er visuelt kontrollert: tabell 3 på side 3, kolonne 3Q26.
SQLite 0039 og D1 0036 erstatter den tidligere tekstbaserte BTG-oppføringen
med alle 11 måltall fra denne tabellen. Beløp er i millioner BRL:

| Måltall | 3Q26-estimat |
| --- | ---: |
| Nettoomsetning | 239,8 |
| Payments | 121,3 |
| SaaS | 47,8 |
| Subscriptions | 49,9 |
| Microfinance | 20,8 |
| Justert EBITDA | 85,5 |
| Justert EBITDA-margin | 35,7 % |
| Justert nettoresultat (Adj. Net Income) | 48,0 |
| Capex | 15,6 |
| Capex / omsetning | 6,5 % |
| OpFCF | 69,9 |

PDF-kilde:
https://content.btgpactual.com/research/files/file/pt-BR/2026-10-08T104612.283_Telecom___Tech___Pr_vias_de_TMT___Parte_II__Intelbras__Totvs__Bemobi_e_LWSA_.pdf

Beløpene er avlest direkte, ikke beregnet fra avrundede vekstrater.
Justert nettoresultat er nå kildebelagt i tabellen; den tidligere
tekstoppføringen «cash profit» ommerkes ikke uten denne separate evidensen.
Hver verdi har kilde, publiseringsdato, side 3 og PDF_TABLE_VERIFIED.
Nattlig HTML-kontroll erstatter ikke et PDF-verifisert estimatsett med bare
prosenttall fra samme publiseringsdato. En nyere rapport erstatter det gamle
settet, slik at tall fra ulike publikasjoner ikke blandes. Andre meglerhus og
rapportdato bevares. Den eksplisitte marginen vises én gang, og capex får
ikke en beat-grense som feilaktig gjør høyere investeringer til et bedre resultat.

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

Kvartalsvisningen viser måltallene nedover i én samlet tabell, med én kolonne
per meglerhus, publiseringsdato og kilde i kolonneoverskriften, og snittet
i siste kolonne. Nye XP-estimater får automatisk egen kolonne når de
lagres i NEXT_QUARTER. Hvert meglerhus har lik vekt per måltall; manglende
verdier utelates, og n viser antall bidrag i hver kolonne. Med bare BTG
tilgjengelig er snittet lik BTGs tall. Flere kilder fra samme meglerhus gir
ikke ekstra vekt. Nyeste publikasjon brukes uten utfylling fra eldre noter.
Beløp og prosenter, justert nettoresultat, ordinært nettoresultat og cash
profit holdes adskilt. En manglende EBITDA-margin kan beregnes fra samme
meglerhus og publikasjon; den merkes med stjerne. Standardvisningen viser
omsetning, justert EBITDA, justert nettoresultat og justert EBITDA-margin.
«Vis flere måltall» utvider tabellen med resten av de 11 BTG-måltallene;
«Vis færre måltall» gjenoppretter standardvisningen. Kortet har begrenset
bredde og kompakte rader. Sammenligningen med siste rapport vises i et
eget kort til høyre på brede skjermer og under forventningene på mindre
skjermer. Sammenligningskortet har også fire måltall som standard og en
egen knapp for å vise resten.

Produksjon følger eksisterende PR → CI → merge → produksjons-CI → deploy,
inkludert D1-migreringen før Worker/asset-deploy. Se `ci-auto-deploy.md`.

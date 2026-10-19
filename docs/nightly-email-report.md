# Nattrapport på e-post

Nattjobben sender én melding med både HTML og ren tekst. Rapporten bygger på
resultatet fra samme Workflow og eksisterende NAV-oppslag; den starter ikke en
ny nattkjøring eller ekstra e-postjobb.

Rapporten viser status, datadato, start/slutt i Europe/Oslo, varighet, jobb-ID,
antall datapunkter og kildestatus. Investor-NAV viser NAV-dato, økonomisk og
konservativ NAV, rabatt og tilgjengelige Life360-tall.

Kjøringsdetaljer viser NAV-beregning, dashboard-cache (inkludert genereringstid),
NAV-historikk og R2-arkivering, samt beståtte datakontroller og tilgjengelige
tellinger per kildesteg. Manglende resultater merkes «ikke rapportert».

Feildelen samler begge feillistene, preflight-blokkeringer/advarsler, kildesvikt
og ikke-kritiske cache-/historikk-/arkiveringsfeil. Identiske steg/feilmeldinger
fjernes. Opptil 15 ulike avvik vises med veiledning; flere henvises til loggen.
Veiledningen beskriver mulige årsaker og oppfølging, ikke en bekreftet diagnose.
Ved SUCCESS med rapporterte avvik blir emnet «OK med avvik», uten at jobbens
lagrede status endres.

Separate GitHub-kontroller av produksjon/NAV/cache kjøres senere. Mailen sier
uttrykkelig at disse ikke inngår i dens status. Cache «OK» betyr at nattjobben
lagret en cache, ikke at en separat offentlig HTTP-avstemming er bestått.

HTML bruker tabeller, inline-stiler og escaped data, uten eksterne bilder,
skrifter eller skript. Typiske token-/passordfelt skjules i feilutdrag, og
knappen tillater bare HTTPS uten brukernavn/passord. Denne endringen sender
ikke en egen testmail.

Forventede NAV-estimater mellom rapportdatoene vises som modellinformasjon,
ikke som advarsler eller avvik i emnet. E-posten bruker samme kvalitetsregler
som statusvisningen. Reelle kvalitetsavvik, øvrige advarsler og blokkeringer
beholdes. Lagrede kjøringsresultater endres ikke.

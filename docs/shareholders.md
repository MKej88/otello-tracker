# Aksjonærer

Investorvisningen bruker Otellos offisielle side for **Top 20 largest shareholders** som primær live-kilde. Selve tabellen leveres av Euronext OMS og vises direkte i investorverktøyet.

Trackerens egne tabeller `shareholder_snapshots` og `shareholder_snapshot_rows` er laget for historikk. Når minst to verifiserte snapshots er lagret, beregnes automatisk:

- største kjøpere og selgere i antall aksjer;
- nye navn inn i Top 20;
- navn som går ut av Top 20;
- Top 20-andel av utstedte aksjer;
- historiske snapshots for senere 4- og 12-ukers sammenligninger.

Otellos publiserte aksjonæridentifikasjon per 4. mars 2026 er lenket som kontrollkilde. Live-kilden og historikklaget holdes adskilt slik at en innbyggingsfeil hos Euronext ikke endrer lagrede historiske data.

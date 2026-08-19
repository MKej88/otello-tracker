# Automatisk produksjonsdeploy

Produksjonsdeploy er satt opp til å starte først etter at `CI` har fullført med `success` for en `push` til `main`.

Deploy-workflowen sjekker ut og verifiserer nøyaktig `head_sha` fra den vellykkede CI-kjøringen før Cloudflare-deploy. `main` er beskyttet av rulesetet `Protect main`, og `CLOUDFLARE_DEPLOY_ENABLED=true` brukes først etter at branch protection er aktiv.

Denne filen ble lagt til som en kontrollert smoke-test av kjeden PR → CI → merge → CI på `main` → automatisk Cloudflare-deploy → produksjonsakseptanse.

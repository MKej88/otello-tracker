# Automatisk produksjonsdeploy

Produksjonsdeploy starter etter at `CI` har fullført med `success` for en `push` til `main`.

Deploy-workflowen sjekker ut og verifiserer eksakt `head_sha` fra den vellykkede CI-kjøringen før Cloudflare-deploy. `main` er beskyttet av rulesetet `Protect main`, og production environment-gaten kontrollerer at automatisk deploy er aktivert.

Flyten er:

```text
pull request
  -> obligatorisk CI
  -> merge til main
  -> CI på main
  -> production environment-gate
  -> Cloudflare deploy av eksakt testet SHA
  -> HTTP-akseptanse mot faktisk produksjon
  -> Worker-rollback dersom etterkontrollen feiler
```

HTTP-akseptansen dekker aktive investorvisninger og sentrale datakontrakter, ikke bare `/api/health`.

D1-migreringer kjøres før Worker deployes. Worker-rollback reverserer ikke disse migreringene, så schemaendringer skal være additive og bakoverkompatible. Se `docs/migration-history.md` og `docs/runbook.md`.

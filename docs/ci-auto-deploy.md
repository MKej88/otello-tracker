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
  -> sjekk ut og verifiser eksakt testet SHA
  -> render og valider produksjonskonfigurasjon
  -> production-shaped Worker dry-run
  -> verifiser Worker-runtime, inkl. Europe/Oslo-tidssonedata
  -> remote D1-migreringer
  -> Cloudflare deploy av eksakt testet SHA
  -> HTTP-akseptanse mot faktisk produksjon
  -> Worker-rollback dersom etterkontrollen feiler
```

Ingen remote D1-endring skal skje før produksjonskonfigurasjonen og Worker-bundlen for den eksakte deploy-SHA-en er validert. Dette gir en ekstra fail-closed gate utover den ordinære `CI`-workflowen.

HTTP-akseptansen dekker aktive investorvisninger og sentrale datakontrakter, inkludert offentlig runtime-status, ikke bare `/api/health`.

D1-migreringer kjøres fortsatt før selve Worker-deployen. Worker-rollback reverserer ikke disse migreringene, så schemaendringer skal være additive og bakoverkompatible. Se `docs/migration-history.md` og `docs/runbook.md`.

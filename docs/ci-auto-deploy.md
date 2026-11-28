# Automatisk produksjonsdeploy

Produksjonsporten starter etter at `CI` har fullført med `success` for en `push` til `main`. Selve utrullingen kan hoppes over bare når produksjonsrevisjonen er bekreftet og alle forskjeller er eksplisitt klassifisert som utenfor produksjonskoden.

Deploy-workflowen sjekker ut og verifiserer eksakt `head_sha` fra den vellykkede CI-kjøringen før Cloudflare-deploy. `main` er beskyttet av rulesetet `Protect main`, og production environment-gaten kontrollerer at automatisk deploy er aktivert.

Flyten er:

```text
pull request
  -> obligatorisk CI
  -> merge til main
  -> CI på main
  -> production environment-gate
  -> sammenlign aktiv produksjonsrevisjon med testet main (utvalgte offline-endringer kan avsluttes her)
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


## Avgrensning av automatiske utrullinger

`tools/production_deploy_scope.py` leser revisjon fra den konfigurerte HTTPS-produksjonsadressens `/api/health`, og sammenligner hele Git-differansen fra denne revisjonen til testet main. Det er ikke nok å sammenligne siste commit: en tidligere ufullstendig utrulling kan ellers bli oversett. Kun Markdown-dokumentasjon og eksplisitt navngitte offline-diagnoseverktøy er unntatt. Ukjente filer, manglende helse/revisjon, ukjent historikk og runtime-/konfigurasjonsendringer beholder ordinær utrulling. Full CI beholdes også for unntatte endringer.

Manuell produksjonsdeploy fra main er fortsatt tilgjengelig og skal brukes ved endrede miljøvariabler eller behov for å distribuere samme kode på nytt. Den rapporterte produksjonsrevisjonen kan ligge bak main når bare dokumentasjon eller godkjente offline-filer er endret; dette er forventet og ikke bevis på manglende utrulling.

# Cloudflare API-token for produksjon

GitHub Actions bruker to separate Cloudflare Account API Token: ett skrive-token for produksjonsdeploy og ett skrivebeskyttet token for drift-/D1-diagnostikk. Tokenverdier skal aldri legges i Git, dokumentasjon, logger eller chat.

## 1. Produksjonsdeploy

GitHub secret:

```text
CLOUDFLARE_API_TOKEN
```

Tokenet brukes bare av produksjonsdeployen og trenger skriveadgang til ressursene som Wrangler faktisk oppdaterer.

### Påkrevde konto-rettigheter

Policy på **Entire Account**:

- `Workers Scripts Write`
- `D1 Write`
- `Workers R2 Storage Write`
- `Account Settings Read`

### Påkrevd domene-rettighet

Egen policy på **Specified Domains → produksjonsdomenet**:

- `Workers Routes Write`

For Otello-produksjon skal domeneressursen begrenses til `otellotracker.com`.

`Workers Routes Write` er nødvendig fordi Wrangler kobler Worker-en til custom domain via Cloudflares zone-baserte Workers Routes API. Uten denne rettigheten kan selve Worker-scriptet og statiske assets bli lastet opp, mens deployen likevel feiler ved `/zones/{zone_id}/workers/routes` med `Authentication error [code: 10000]`.

Ingen DNS Write-, Zone Write-, WAF Write-, KV- eller bredere administratorrettigheter er nødvendige for den normale GitHub-deployen.

## 2. Skrivebeskyttet produksjonsdiagnostikk

GitHub secret:

```text
CLOUDFLARE_READ_TOKEN
```

Den planlagte GitHub-workflowen `.github/workflows/cloudflare-workflow-diagnostics.yml` bruker dette tokenet til å lese status fra Cloudflare Workflows og produksjons-D1 etter nattkjøringen.

På **Entire Account** skal tokenet ha minst:

- `Workers Scripts Read`
- `D1 Read`

Tokenet skal **ikke** ha Workers-, D1-, R2- eller andre skrive-rettigheter. Dersom diagnostikken senere utvides til å lese R2-arkiv eller live Worker-logger, kan henholdsvis `Workers R2 Storage Read` eller `Workers Tail Read` legges til eksplisitt da. De er ikke nødvendige for dagens Workflow-/D1-diagnostikk.

Diagnostikken bruker samme konto-ID som deployen:

```text
CLOUDFLARE_ACCOUNT_ID
```

Den skrivebeskyttede workflowen skal ikke trigge Cloudflare Workflows, endre D1 eller utføre andre produksjonswrites. Et avvik rapporteres kun gjennom GitHub Actions.

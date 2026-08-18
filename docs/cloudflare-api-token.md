# Cloudflare API-token for produksjonsdeploy

GitHub Actions bruker et avgrenset Cloudflare Account API Token.

## Påkrevde konto-rettigheter

Policy på **Entire Account**:

- `Workers Scripts Write`
- `D1 Write`
- `Workers R2 Storage Write`
- `Account Settings Read`

## Påkrevd domene-rettighet

Egen policy på **Specified Domains → produksjonsdomenet**:

- `Workers Routes Write`

For Otello-produksjon skal domeneressursen begrenses til `otellotracker.com`.

`Workers Routes Write` er nødvendig fordi Wrangler kobler Worker-en til custom domain via Cloudflares zone-baserte Workers Routes API. Uten denne rettigheten kan selve Worker-scriptet og statiske assets bli lastet opp, mens deployen likevel feiler ved `/zones/{zone_id}/workers/routes` med `Authentication error [code: 10000]`.

Ingen DNS Write-, Zone Write-, WAF Write-, KV- eller bredere administratorrettigheter er nødvendige for den normale GitHub-deployen.

## GitHub secret

Tokenverdien lagres kun som:

```text
CLOUDFLARE_API_TOKEN
```

under GitHub `production` environment. Tokenverdien skal ikke legges i Git, dokumentasjon, logger eller chat.

const pendingJson = new Map<string, Promise<unknown>>();
const resolvedJson = new Map<string, { expiresAt: number; value: unknown }>();
const NAVIGATION_CACHE_MS = 30_000;
const NAV_PERIOD_BUNDLE_URL = "/api/dashboard/nav-periods";

type NavPeriodBundle = {
  ready?: boolean;
  periods?: Record<string, unknown>;
};

function startJsonRequest(url: string): Promise<unknown> {
  const cached = resolvedJson.get(url);
  if (cached && cached.expiresAt > Date.now()) return Promise.resolve(cached.value);
  if (cached) resolvedJson.delete(url);

  const existing = pendingJson.get(url);
  if (existing) return existing;

  const request = fetch(url)
    .then((response) => {
      if (!response.ok) throw new Error(`API-feil: ${response.status}`);
      return response.json() as Promise<unknown>;
    })
    .then((value) => {
      resolvedJson.set(url, {
        expiresAt: Date.now() + NAVIGATION_CACHE_MS,
        value,
      });
      return value;
    })
    .catch((error: unknown) => {
      pendingJson.delete(url);
      throw error;
    })
    .finally(() => {
      if (pendingJson.get(url) === request) pendingJson.delete(url);
    });
  pendingJson.set(url, request);
  return request;
}

/**
 * Start one compact request containing every nightly materialized NAV period.
 * Each existing period URL is seeded with the same payload shape NavPageV2 already consumes.
 * If the nightly bundle is unavailable during rollout, fall back to the existing endpoint.
 */
export function preloadNavPeriodBundle(periodUrls: Record<string, string>): void {
  const bundleRequest = startJsonRequest(NAV_PERIOD_BUNDLE_URL);

  for (const [periodKey, url] of Object.entries(periodUrls)) {
    const cached = resolvedJson.get(url);
    if (cached && cached.expiresAt > Date.now()) continue;
    if (pendingJson.has(url)) continue;

    let derivedRequest: Promise<unknown>;
    derivedRequest = bundleRequest
      .then((value) => {
        const bundle = value as NavPeriodBundle;
        const estimated = bundle.periods?.[periodKey];
        if (estimated == null) throw new Error(`Materialisert NAV-periode mangler: ${periodKey}`);
        const payload = { estimated };
        resolvedJson.set(url, {
          expiresAt: Date.now() + NAVIGATION_CACHE_MS,
          value: payload,
        });
        return payload;
      })
      .catch(async () => {
        if (pendingJson.get(url) === derivedRequest) pendingJson.delete(url);
        return startJsonRequest(url);
      })
      .finally(() => {
        if (pendingJson.get(url) === derivedRequest) pendingJson.delete(url);
      });
    pendingJson.set(url, derivedRequest);
  }
}

/** Start dataarbeidet samtidig med innlasting av den kode-splittede visningen. */
export function preloadJson(url: string): void {
  void startJsonRequest(url).catch(() => undefined);
}

/** Gjenbruk navigasjonsforespørselen i stedet for å starte en duplikat. */
export async function fetchPreloadedJson<T>(url: string): Promise<T> {
  const request = startJsonRequest(url);
  try {
    return await request as T;
  } finally {
    if (pendingJson.get(url) === request) pendingJson.delete(url);
  }
}

const pendingJson = new Map<string, Promise<unknown>>();
const resolvedJson = new Map<string, { expiresAt: number; value: unknown }>();
const NAVIGATION_CACHE_MS = 30_000;

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

const pendingJson = new Map<string, Promise<unknown>>();

function startJsonRequest(url: string): Promise<unknown> {
  const existing = pendingJson.get(url);
  if (existing) return existing;

  const request = fetch(url)
    .then((response) => {
      if (!response.ok) throw new Error(`API-feil: ${response.status}`);
      return response.json() as Promise<unknown>;
    })
    .catch((error: unknown) => {
      pendingJson.delete(url);
      throw error;
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

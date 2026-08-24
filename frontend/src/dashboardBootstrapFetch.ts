export type BootstrapComponent = "summary" | "economic" | "quotes" | "forecast";

type BootstrapPayload = {
  summary?: unknown;
  economic?: unknown;
  quotes?: unknown;
  forecast?: unknown;
  meta?: {
    source?: string;
    snapshot_version?: number | null;
    generated_at?: string | null;
    server_ms?: number | null;
  };
};

type StoredBootstrap = {
  cacheVersion: number;
  storedAt: number;
  payload: BootstrapPayload;
};

const COMPONENT_BY_PATH: Record<string, BootstrapComponent> = {
  "/api/dashboard/summary": "summary",
  "/api/dashboard/economic": "economic",
  "/api/market/quotes": "quotes",
  "/api/buybacks/forecast": "forecast"
};

const CLIENT_CACHE_KEY = "otello.dashboard.bootstrap.v1";
const CLIENT_CACHE_VERSION = 1;
const CLIENT_CACHE_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;

let installed = false;
let bootstrapPromise: Promise<BootstrapPayload | null> | null = null;
const servedFromBootstrap = new Set<BootstrapComponent>();

function requestUrl(input: RequestInfo | URL): URL | null {
  try {
    if (typeof input === "string") return new URL(input, window.location.origin);
    if (input instanceof URL) return new URL(input.href, window.location.origin);
    return new URL(input.url, window.location.origin);
  } catch {
    return null;
  }
}

function requestMethod(input: RequestInfo | URL, init?: RequestInit): string {
  if (init?.method) return init.method.toUpperCase();
  if (typeof Request !== "undefined" && input instanceof Request) return input.method.toUpperCase();
  return "GET";
}

function isObject(value: unknown): value is Record<string, unknown> {
  return value != null && typeof value === "object";
}

function completeBootstrap(payload: BootstrapPayload | null): payload is BootstrapPayload {
  return payload != null
    && isObject(payload.summary)
    && isObject(payload.economic)
    && isObject(payload.quotes)
    && isObject(payload.forecast);
}

function loadStoredBootstrap(): StoredBootstrap | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(CLIENT_CACHE_KEY);
    if (!raw) return null;
    const stored = JSON.parse(raw) as Partial<StoredBootstrap>;
    if (stored.cacheVersion !== CLIENT_CACHE_VERSION
      || typeof stored.storedAt !== "number"
      || Date.now() - stored.storedAt > CLIENT_CACHE_MAX_AGE_MS
      || !completeBootstrap(stored.payload ?? null)) {
      window.localStorage.removeItem(CLIENT_CACHE_KEY);
      return null;
    }
    return stored as StoredBootstrap;
  } catch {
    return null;
  }
}

function storeBootstrap(payload: BootstrapPayload): void {
  if (typeof window === "undefined" || !completeBootstrap(payload)) return;
  try {
    const stored: StoredBootstrap = {
      cacheVersion: CLIENT_CACHE_VERSION,
      storedAt: Date.now(),
      payload
    };
    window.localStorage.setItem(CLIENT_CACHE_KEY, JSON.stringify(stored));
  } catch {
    // Storage can be unavailable in private/restricted browser contexts. Network bootstrap remains the fallback.
  }
}

export function getCachedDashboardComponent<T>(component: BootstrapComponent): T | null {
  const stored = loadStoredBootstrap();
  const value = stored?.payload[component];
  return isObject(value) ? value as T : null;
}

async function fetchBootstrap(originalFetch: typeof window.fetch): Promise<BootstrapPayload | null> {
  try {
    const response = await originalFetch("/api/dashboard/bootstrap");
    if (!response.ok) return null;
    const payload = await response.json() as BootstrapPayload;
    if (!completeBootstrap(payload)) return null;
    storeBootstrap(payload);
    return payload;
  } catch {
    return null;
  }
}

function syntheticResponse(payload: object, source: "HIT" | "CLIENT_CACHE"): Response {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: {
      "Content-Type": "application/json",
      "X-Otello-Bootstrap": source
    }
  });
}

/**
 * Coalesce the first dashboard requests into one bootstrap request.
 * A bounded last-good browser copy makes repeat first paint independent of Worker cold start;
 * the network bootstrap is still started immediately and later polling uses dedicated endpoints.
 */
export function installDashboardBootstrapFetch(): void {
  if (installed || typeof window === "undefined") return;
  installed = true;

  const originalFetch = window.fetch.bind(window);
  const cached = loadStoredBootstrap();

  // Start revalidation before React effects issue their first API request.
  bootstrapPromise = fetchBootstrap(originalFetch);

  window.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = requestUrl(input);
    const component = url && url.search === "" ? COMPONENT_BY_PATH[url.pathname] : undefined;
    const canBootstrap = component != null
      && requestMethod(input, init) === "GET"
      && !servedFromBootstrap.has(component);

    if (!canBootstrap || component == null) {
      return originalFetch(input, init);
    }

    const cachedComponent = cached?.payload[component];
    if (isObject(cachedComponent)) {
      servedFromBootstrap.add(component);
      return syntheticResponse(cachedComponent, "CLIENT_CACHE");
    }

    const payload = await bootstrapPromise;
    const componentPayload = payload?.[component];
    if (!isObject(componentPayload)) {
      return originalFetch(input, init);
    }

    servedFromBootstrap.add(component);
    return syntheticResponse(componentPayload, "HIT");
  };
}

type BootstrapComponent = "summary" | "economic" | "quotes" | "forecast";

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

const COMPONENT_BY_PATH: Record<string, BootstrapComponent> = {
  "/api/dashboard/summary": "summary",
  "/api/dashboard/economic": "economic",
  "/api/market/quotes": "quotes",
  "/api/buybacks/forecast": "forecast"
};

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

async function fetchBootstrap(originalFetch: typeof window.fetch): Promise<BootstrapPayload | null> {
  try {
    const response = await originalFetch("/api/dashboard/bootstrap");
    if (!response.ok) return null;
    const payload = await response.json() as BootstrapPayload;
    return payload && typeof payload === "object" ? payload : null;
  } catch {
    return null;
  }
}

/**
 * Coalesce the first dashboard requests into one bootstrap request.
 * Later polling keeps using the original dedicated endpoints, so this only changes
 * the first-load request fan-out and has an automatic fallback if bootstrap fails.
 */
export function installDashboardBootstrapFetch(): void {
  if (installed || typeof window === "undefined") return;
  installed = true;

  const originalFetch = window.fetch.bind(window);

  window.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = requestUrl(input);
    const component = url && url.search === "" ? COMPONENT_BY_PATH[url.pathname] : undefined;
    const canBootstrap = component != null
      && requestMethod(input, init) === "GET"
      && !servedFromBootstrap.has(component);

    if (!canBootstrap || component == null) {
      return originalFetch(input, init);
    }

    if (bootstrapPromise == null) {
      bootstrapPromise = fetchBootstrap(originalFetch);
    }

    const payload = await bootstrapPromise;
    const componentPayload = payload?.[component];
    if (componentPayload == null || typeof componentPayload !== "object") {
      return originalFetch(input, init);
    }

    servedFromBootstrap.add(component);
    return new Response(JSON.stringify(componentPayload), {
      status: 200,
      headers: {
        "Content-Type": "application/json",
        "X-Otello-Bootstrap": "HIT"
      }
    });
  };
}

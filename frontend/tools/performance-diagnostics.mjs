/** Bounded, privacy-safe diagnostics for synthetic Chrome cold-load probes. */
const MAX_ISSUES = 12;
const MAX_PENDING = 8;

function apiPath(raw, origin) {
  try {
    const url = new URL(raw);
    return url.origin === origin && url.pathname.startsWith("/api/")
      ? url.pathname : null;
  } catch {
    return null;
  }
}

function networkCategory(errorText) {
  const error = String(errorText || "").toLowerCase();
  if (error.includes("timed_out") || error.includes("timeout")) return "network_timeout";
  if (error.includes("name_not_resolved") || error.includes("dns")) return "dns";
  if (error.includes("cert_") || error.includes("ssl_")) return "tls";
  if (error.includes("blocked")) return "blocked";
  if (error.includes("connection_")) return "connection";
  return "network";
}

export function httpCategory(status) {
  if (status === 429) return "rate_limited";
  if (status >= 500) return "server_http_error";
  if (status >= 400) return "client_http_error";
  return "ok";
}

/** Rate-limit aware API sampling. Keep all waits outside measured response timings. */
export const API_PROBE_INTERVAL_MS = 1250;

export function parseRetryAfterMs(value, nowMs = Date.now()) {
  if (value == null || !String(value).trim()) return null;
  const raw = String(value).trim();
  if (/^-?\d+(?:\.\d+)?$/.test(raw)) {
    const seconds = Number(raw);
    return Number.isFinite(seconds) && seconds >= 0 ? Math.ceil(seconds * 1000) : null;
  }
  // Only parse RFC-style HTTP dates, not arbitrary strings Date.parse accepts.
  if (!/^[A-Za-z]{3},\s+\d{1,2}\s+[A-Za-z]{3}\s+\d{4}\s+\d{2}:\d{2}:\d{2}\s+GMT$/i.test(raw)) {
    return null;
  }
  const date = Date.parse(raw);
  return Number.isFinite(date) ? Math.max(0, date - nowMs) : null;
}

export function isRateLimitError(error) {
  return error?.status === 429;
}

/**
 * Retry only HTTP 429. Respect Retry-After, including a long backoff by
 * skipping the probe rather than retrying before the requested cooldown.
 * The caller measures only the final HTTP request, not the waiting period.
 */
export async function fetchWithRateLimitRetry(url, {
  fetchFn = fetch,
  sleepFn = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
  beforeAttempt = async () => {},
  maxRetries = 2,
} = {}) {
  let rateLimitedAttempts = 0;
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    await beforeAttempt();
    const response = await fetchFn(url, {
      signal: AbortSignal.timeout(20000),
      headers: { accept: "application/json" },
    });
    if (response.status !== 429) return { response, rateLimitedAttempts };

    rateLimitedAttempts++;
    const retryAfterMs = parseRetryAfterMs(response.headers.get("retry-after"));
    await response.body?.cancel();
    // A long Retry-After means the server explicitly asked us not to probe
    // again during this run. Never override it with our shorter backoff.
    if (attempt === maxRetries || (retryAfterMs != null && retryAfterMs > 60000)) {
      const error = new Error("HTTP 429 (rate limited)");
      error.status = 429;
      error.rateLimitedAttempts = rateLimitedAttempts;
      throw error;
    }
    await sleepFn(retryAfterMs ?? Math.min(15000, 5000 * 2 ** attempt));
  }
}

/** Only an actual fetch deadline should be retried; never retry HTTP 4xx/5xx or DNS/TLS errors. */
export function isTimeoutError(error) {
  return error?.name === "TimeoutError" ||
    (error?.name === "AbortError" && error?.cause?.name === "TimeoutError");
}

/**
 * Retry one timed-out API sample, including a timed-out response body.
 * Backoff happens outside measured response times, and only the successful
 * attempt is returned. Exhausted deadlines remain genuine monitoring errors.
 */
export async function retryOnTimeout(runAttempt, {
  sleepFn = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
  maxRetries = 1,
  retryDelayMs = 2000,
} = {}) {
  let timeoutRetries = 0;
  while (true) {
    try {
      return { value: await runAttempt(), timeoutRetries };
    } catch (error) {
      if (!isTimeoutError(error)) throw error;
      timeoutRetries++;
      if (timeoutRetries > maxRetries) {
        error.timeoutAttempts = timeoutRetries;
        throw error;
      }
      await sleepFn(retryDelayMs * timeoutRetries);
    }
  }
}

/** Never store full URLs, query strings, headers, response bodies or raw network errors. */
export function createApiDiagnostics(origin) {
  const requests = new Map();
  const issues = [];
  const append = (entry) => {
    issues.push(entry);
    if (issues.length > MAX_ISSUES) issues.shift();
  };
  return {
    onEvent(method, params = {}) {
      const id = params.requestId;
      if (method === "Network.requestWillBeSent") {
        const path = apiPath(params.request?.url, origin);
        if (id && path) requests.set(id, path);
      } else if (method === "Network.responseReceived") {
        const path = (id && requests.get(id)) || apiPath(params.response?.url, origin);
        const status = Number(params.response?.status);
        if (path && Number.isInteger(status) && status >= 400) {
          append({ path, status, category: httpCategory(status) });
        }
      } else if (method === "Network.loadingFailed") {
        const path = id && requests.get(id);
        if (path && !params.canceled) {
          append({ path, status: null, category: networkCategory(params.errorText) });
        }
        if (id) requests.delete(id);
      } else if (method === "Network.loadingFinished") {
        if (id) requests.delete(id);
      }
    },
    snapshot() {
      return {
        apiIssues: [...issues],
        pendingApiPaths: [...new Set(requests.values())].slice(0, MAX_PENDING),
      };
    },
  };
}

/** Interpret what was actually seen, not all non-ready screens as 'slow'. */
export function classifyColdFailure(error, pageState, network) {
  const apiIssues = Array.isArray(network?.apiIssues) ? network.apiIssues : [];
  const pendingApiPaths = Array.isArray(network?.pendingApiPaths)
    ? network.pendingApiPaths : [];
  const http = apiIssues.findLast((item) => Number.isInteger(item.status));
  const transport = apiIssues.findLast((item) => item.status == null);
  const message = String(error?.message || "");
  const timedOut = message.includes("No valid main content within");
  const sawDataError = Boolean(pageState?.error) || message.includes("Investor data error");
  const missingData = Boolean(pageState?.unavailable);

  let category;
  if (http) category = http.category;
  else if (transport) category = transport.category;
  else if (missingData) category = "data_unavailable";
  else if (sawDataError) category = "application_data_error";
  else if (timedOut && (pageState?.loading || pendingApiPaths.length)) category = "data_load_timeout";
  else if (timedOut) category = "content_timeout";
  else category = "browser_probe_error";

  return {
    category,
    page: {
      headingMatches: Boolean(pageState?.headingMatches),
      markerFound: Boolean(pageState?.markerFound),
      loading: Boolean(pageState?.loading),
      unavailable: missingData,
      error: sawDataError,
    },
    apiIssues,
    pendingApiPaths,
  };
}

/** Retry exactly once in a new browser profile; preserve both attempts. */
export async function probeColdWithRetry(runAttempt, wait = async () => {}) {
  const attempts = [];
  for (let attempt = 1; attempt <= 2; attempt++) {
    try {
      const metrics = await runAttempt(attempt);
      attempts.push({ attempt, outcome: "success", firstDataMs: metrics.firstDataMs });
      return { ok: true, metrics, attempts };
    } catch (error) {
      attempts.push({
        attempt, outcome: "failed",
        diagnosis: error?.diagnosis || classifyColdFailure(error, null, null),
      });
      if (attempt === 1) await wait(attempts[0]);
    }
  }
  return { ok: false, attempts };
}

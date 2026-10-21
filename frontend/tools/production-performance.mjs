/**
 * Production-only synthetic monitoring. No client telemetry or UI dependencies.
 * Runs in GitHub Actions with a fresh headless Chrome profile per route.
 */
import { spawn } from "node:child_process";
import { appendFileSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { performance } from "node:perf_hooks";
import {
  API_PROBE_INTERVAL_MS, classifyColdFailure, createApiDiagnostics,
  fetchWithRateLimitRetry, isRateLimitError, probeColdWithRetry,
} from "./performance-diagnostics.mjs";

const base = new URL(process.env.OTELLO_SITE_URL || "https://otellotracker.com/");
const chromeBin = process.env.CHROME_BIN || "google-chrome";
const reportPath = process.env.PERF_REPORT_PATH || "performance-report.json";
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** All 12 investor views, with a DOM marker that is only present when
 * the main content has actually rendered (not only the navigation shell).
 */
const ROUTES = [
  { label: "Oversikt", hash: "#oversikt", heading: "Otello investoroversikt", selector: ".overviewV3 .overviewNavCard h2", kind: "price" },
  { label: "NAV", hash: "#nav", heading: "NAV", selector: ".navV2 .estimatedHero h2", kind: "price" },
  { label: "NAV-sensitivitet", hash: "#nav-sensitivitet", heading: "NAV-sensitivitet", selector: ".sensitivityPage .sensitivityMatrixCard" },
  { label: "Historikk", hash: "#historikk", heading: "Historisk NAV-rabatt", selector: ".historyV2 .historyAxisCard" },
  { label: "Tilbakekjøpsprogram", hash: "#tilbakekjop", heading: "Tilbakekjøpsprogram", selector: ".buybackPage .buybackHero" },
  { label: "Cash", hash: "#cash", heading: "Cash & kapitalallokering", selector: ".cashPage .cashHero" },
  { label: "Bemobi", hash: "#bemobi", heading: "Bemobi", selector: ".bemobiPage .bemobiCleanHero" },
  { label: "BRL/NOK", hash: "#brl-nok", heading: "BRL/NOK", selector: ".fxPage .fxHero" },
  { label: "Brasil", hash: "#brasil", heading: "Brasil", selector: ".brazilPage .brazilInvestorHero" },
  { label: "Konsensus", hash: "#konsensus", heading: "Konsensus", selector: ".consensusPage .consensusHero" },
  { label: "Nyheter", hash: "#nyheter", heading: "Nyheter og hendelser", selector: ".newsEventsPage .newsHero", kind: "news" },
  { label: "Datakvalitet", hash: "#datakvalitet", heading: "Datakvalitet", selector: ".dataQualityPage .qualityTrustHero", kind: "quality" },
];

function assertRouteCatalog() {
  const uniqueHashes = new Set(ROUTES.map((route) => route.hash));
  if (ROUTES.length !== 12 || uniqueHashes.size !== ROUTES.length) {
    throw new Error("The synthetic route catalogue must cover all 12 views without duplicates");
  }
}
assertRouteCatalog();

if (base.protocol !== "https:" && base.hostname !== "127.0.0.1") {
  throw new Error("Synthetic performance tests require HTTPS or local loopback.");
}

function rounded(ms) {
  return Math.round(ms);
}

function median(values) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.floor((sorted.length - 1) / 2)];
}

/** Fetch timing to headers (approx. externally observed TTFB) and full body. */
let nextApiRequestAt = 0;

/** Limit the aggregate request rate, including retries, across API endpoints. */
async function paceApiRequest() {
  const remaining = nextApiRequestAt - Date.now();
  if (remaining > 0) await sleep(remaining);
  nextApiRequestAt = Date.now() + API_PROBE_INTERVAL_MS;
}

/** The wait/retry duration is intentionally excluded from response-time samples. */
async function probeApi(path) {
  const samples = [];
  let rateLimitedAttempts = 0;
  for (let i = 0; i < 3; i++) {
    let started;
    const { response, rateLimitedAttempts: retries } = await fetchWithRateLimitRetry(
      new URL(path, base), {
        beforeAttempt: paceApiRequest,
        fetchFn: (...args) => {
          started = performance.now();
          return fetch(...args);
        },
      },
    );
    rateLimitedAttempts += retries;
    const headersMs = rounded(performance.now() - started);
    const bytes = (await response.arrayBuffer()).byteLength;
    const totalMs = rounded(performance.now() - started);
    if (!response.ok) throw new Error("HTTP " + response.status + " for " + path);
    samples.push({
      headersMs, totalMs, bytes, status: response.status,
      cfCacheStatus: response.headers.get("cf-cache-status") || "ikke oppgitt",
      ageSeconds: Number(response.headers.get("age")) || 0,
    });
  }
  return {
    endpoint: path,
    medianHeadersMs: median(samples.map((sample) => sample.headersMs)),
    medianTotalMs: median(samples.map((sample) => sample.totalMs)),
    maxTotalMs: Math.max(...samples.map((sample) => sample.totalMs)),
    responseBytes: samples.at(-1).bytes,
    cfCacheStatus: samples.map((sample) => sample.cfCacheStatus),
    ageSeconds: samples.map((sample) => sample.ageSeconds),
    rateLimitedAttempts,
  };
}

async function stopChrome(chrome) {
  if (chrome.exitCode !== null || chrome.signalCode !== null) return;
  chrome.kill("SIGTERM");
  const deadline = Date.now() + 3000;
  while (chrome.exitCode === null && chrome.signalCode === null && Date.now() < deadline) {
    await sleep(50);
  }
  if (chrome.exitCode === null && chrome.signalCode === null) chrome.kill("SIGKILL");
}

async function devtoolsPort(profileDir, chrome, lastError) {
  const deadline = Date.now() + 20000;
  while (Date.now() < deadline) {
    if (chrome.exitCode !== null || chrome.signalCode !== null) {
      throw new Error("Chrome stopped before DevTools: " + lastError());
    }
    try {
      const port = Number(readFileSync(join(profileDir, "DevToolsActivePort"), "utf8").split(/\r?\n/)[0]);
      if (Number.isInteger(port) && port > 0) {
        const response = await fetch("http://127.0.0.1:" + port + "/json/version", {
          signal: AbortSignal.timeout(1000),
        });
        if (response.ok) return port;
      }
    } catch {
      // The ephemeral debugging socket may not be ready yet.
    }
    await sleep(150);
  }
  throw new Error("Chrome DevTools timeout: " + lastError());
}

class CdpSession {
  constructor(socketUrl) {
    this.ws = new WebSocket(socketUrl);
    this.serial = 0;
    this.pending = new Map();
    this.handlers = new Map();
  }
  on(method, listener) {
    const listeners = this.handlers.get(method) || [];
    listeners.push(listener);
    this.handlers.set(method, listeners);
  }
  async connect() {
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("CDP socket timeout")), 10000);
      this.ws.addEventListener("open", () => { clearTimeout(timer); resolve(); }, { once: true });
      this.ws.addEventListener("error", () => { clearTimeout(timer); reject(new Error("CDP connection failed")); }, { once: true });
    });
    this.ws.addEventListener("message", (event) => {
      const message = JSON.parse(event.data);
      if (message.method) {
        for (const listener of this.handlers.get(message.method) || []) {
          listener(message.params || {});
        }
        return;
      }
      if (!message.id) return;
      const request = this.pending.get(message.id);
      if (!request) return;
      this.pending.delete(message.id);
      if (message.error) request.reject(new Error(JSON.stringify(message.error)));
      else request.resolve(message.result || {});
    });
  }
  send(method, params = {}) {
    const id = ++this.serial;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }
  async evaluate(expression) {
    const response = await this.send("Runtime.evaluate", {
      expression, awaitPromise: true, returnByValue: true,
    });
    if (response.exceptionDetails) throw new Error(JSON.stringify(response.exceptionDetails));
    return response.result?.value;
  }
  close() {
    this.ws.close();
  }
}

function screenState() {
  const route = routeDefinitions.find((item) => item.hash === location.hash.toLowerCase());
  const heading = document.querySelector(".investorTopbar h1")?.textContent?.trim();
  const marker = route ? document.querySelector(route.selector) : null;
  let ready = Boolean(route && marker && heading === route.heading);
  if (ready && route.kind === "price") {
    ready = marker.textContent.includes("kr") && !marker.querySelector(".loadingPlaceholder");
  }
  if (ready && route.kind === "news") {
    ready = !document.querySelector(".loadingPlaceholderNews, .loadingPlaceholderCalendar");
  }
  if (ready && route.kind === "quality") {
    ready = !document.querySelector(".qualityTrustLead small")?.textContent?.trim().endsWith("–");
  }
  const error = Boolean(document.querySelector(".brazilError")) ||
    Boolean(document.querySelector(".resourceNoticeError")) ||
    (document.body?.innerText || "").includes("Kunne ikke hente investordata.") ||
    (document.body?.innerText || "").includes("Kunne ikke hente NAV-historikk.") ||
    (document.body?.innerText || "").includes("Kunne ikke hente Bemobi-data.") ||
    (document.body?.innerText || "").includes("Kunne ikke hente konsensusdata.") ||
    (document.body?.innerText || "").includes("Kunne ikke hente NAV-sammensetningen.");
  return {
    ready, error, label: route?.label || null, heading,
    headingMatches: Boolean(route && heading === route.heading),
    markerFound: Boolean(marker),
    loading: Boolean(document.querySelector(".loadingPlaceholderPage, .loadingPlaceholder, .loadingPlaceholderNews")),
    unavailable: Boolean(document.querySelector(".fxError, .bemobiNotice, .brazilError, .resourceNoticeError")),
  };
}

/**
 * Installed only by CDP in synthetic Chrome, before React loads. A MutationObserver
 * records the FIRST animation frame after a route's real data marker is ready.
 * That removes the ~120ms CDP poll/scheduling artifact from SPA measurements.
 */
function syntheticObserver(routeDefinitions, screenState) {
  const readyAt = Object.create(null);
  const longTasks = [];
  let pendingFrame = false;
  const monitor = {
    readyAt, longTasks,
    arm(hash) {
      delete readyAt[hash];
      schedule();
    },
  };
  Object.defineProperty(window, "__otelloSynthetic", { value: monitor });

  function check() {
    pendingFrame = false;
    const state = screenState();
    if (state?.ready && state.label) {
      const hash = location.hash.toLowerCase();
      if (readyAt[hash] == null) readyAt[hash] = performance.now();
    }
  }
  function schedule() {
    if (pendingFrame) return;
    pendingFrame = true;
    requestAnimationFrame(check);
  }

  new MutationObserver(schedule).observe(document, {
    childList: true, characterData: true, subtree: true,
  });
  window.addEventListener("hashchange", schedule);
  document.addEventListener("DOMContentLoaded", schedule);
  try {
    new PerformanceObserver((list) => {
      for (const item of list.getEntries()) {
        if (longTasks.length < 200) {
          longTasks.push({ start: item.startTime, duration: item.duration });
        }
      }
    }).observe({ type: "longtask", buffered: true });
  } catch {
    // Long Tasks API may not be supported in some Chrome versions.
  }
  schedule();
}

function observerInjection() {
  return "(" + syntheticObserver.toString() + ")(" +
    JSON.stringify(ROUTES) + ", (" + screenState.toString() + "))";
}

function routeStatusScript() {
  return "(() => { const routeDefinitions = " + JSON.stringify(ROUTES) +
    "; return (" + screenState.toString() + ")(); })()";
}

async function waitForRoute(session, route, timeoutMs = 25000) {
  const deadline = Date.now() + timeoutMs;
  let state;
  while (Date.now() < deadline) {
    state = await session.evaluate(routeStatusScript());
    if (state?.error) throw new Error("Investor data error on " + route.hash);
    if (state?.unavailable && !state?.ready) {
      throw new Error("Investor data unavailable on " + route.hash);
    }
    if (state?.ready && state.label === route.label) return;
    await sleep(120);
  }
  throw new Error("No valid main content within " + timeoutMs + "ms on " + route.hash +
    "; last state: " + JSON.stringify(state));
}

function metricsScript(transitionStart = false) {
  return "(async () => { await new Promise(resolve => requestAnimationFrame(resolve)); " +
    "const routeDefinitions = " + JSON.stringify(ROUTES) + "; " +
    "const screenState = (" + screenState.toString() + "); " +
    "return (" + extractBrowserMetrics.toString() + ")(" +
    (transitionStart ? "window.__otelloPerfNavigationStart" : "0") +
    "); })()";
}

function extractBrowserMetrics(transitionStartMs = 0) {
  const status = screenState();
  const now = performance.now();
  const markerAt = window.__otelloSynthetic?.readyAt?.[location.hash.toLowerCase()];
  // Keep the first-ready timestamp; never measure a second CDP poll as "load time".
  const firstReadyAt = Number.isFinite(markerAt) && markerAt >= transitionStartMs
    ? markerAt : now;
  const nav = performance.getEntriesByType("navigation")[0];
  const resources = performance.getEntriesByType("resource")
    .filter((entry) => entry.startTime >= transitionStartMs && entry.startTime <= firstReadyAt)
    .map((entry) => {
      try {
        const url = new URL(entry.name);
        if (url.origin !== location.origin) return null;
        return {
          path: url.pathname,
          durationMs: Math.round(entry.duration),
          responseEndMs: Math.round(entry.responseEnd),
          transferBytes: entry.transferSize || 0,
          decodedBytes: entry.decodedBodySize || 0,
          initiator: entry.initiatorType,
        };
      } catch {
        return null;
      }
    })
    .filter(Boolean);
  const apiResources = resources
    .filter((entry) => entry.path.startsWith("/api/"))
    .sort((a, b) => b.durationMs - a.durationMs)
    .slice(0, 5);
  const scriptResources = resources
    .filter((entry) => entry.initiator === "script" ||
      /\.(?:m?js)$/.test(entry.path))
    .sort((a, b) => b.durationMs - a.durationMs)
    .slice(0, 5);
  const longTasks = (window.__otelloSynthetic?.longTasks || [])
    .filter((task) => task.start < firstReadyAt &&
      task.start + task.duration > transitionStartMs)
    .map((task) => Math.min(firstReadyAt, task.start + task.duration) -
      Math.max(transitionStartMs, task.start));
  const domReadyAt = nav?.domContentLoadedEventEnd ?? null;
  return {
    firstDataMs: Math.round(firstReadyAt - transitionStartMs),
    documentTtfbMs: !transitionStartMs && nav ? Math.round(nav.responseStart) : null,
    domReadyMs: !transitionStartMs && domReadyAt != null ? Math.round(domReadyAt) : null,
    domToDataMs: !transitionStartMs && domReadyAt != null
      ? Math.round(Math.max(0, firstReadyAt - domReadyAt)) : null,
    apiResources,
    scriptResources,
    longTaskCount: longTasks.length,
    longTaskTotalMs: Math.round(longTasks.reduce((sum, value) => sum + value, 0)),
    observerCaptured: Number.isFinite(markerAt) && markerAt >= transitionStartMs,
    status,
  };
}

async function probeBrowserAttempt(hash) {
  const profileDir = mkdtempSync(join(tmpdir(), "otello-prod-perf-"));
  const chrome = spawn(chromeBin, [
    "--headless=new", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
    "--disable-background-networking", "--disable-extensions", "--no-first-run",
    "--window-size=1440,1100", "--remote-debugging-address=127.0.0.1",
    "--remote-debugging-port=0", "--user-data-dir=" + profileDir, "about:blank",
  ], { stdio: ["ignore", "ignore", "pipe"] });
  let stderr = "";
  chrome.stderr.on("data", (data) => {
    stderr = (stderr + String(data)).slice(-2000);
  });
  let session = null;
  const apiTrace = createApiDiagnostics(base.origin);
  try {
    const port = await devtoolsPort(profileDir, chrome, () => stderr);
    const response = await fetch("http://127.0.0.1:" + port + "/json/new?about:blank", {
      method: "PUT", signal: AbortSignal.timeout(5000),
    });
    if (!response.ok) throw new Error("Unable to create Chrome tab");
    const tab = await response.json();
    session = new CdpSession(tab.webSocketDebuggerUrl);
    await session.connect();
    for (const method of [
      "Network.requestWillBeSent", "Network.responseReceived",
      "Network.loadingFailed", "Network.loadingFinished",
    ]) session.on(method, (params) => apiTrace.onEvent(method, params));
    await session.send("Network.enable");
    await session.send("Runtime.enable");
    await session.send("Page.enable");
    await session.send("Page.addScriptToEvaluateOnNewDocument", {
      source: observerInjection(),
    });
    const pageUrl = new URL("/" + hash, base).toString();
    await session.send("Page.navigate", { url: pageUrl });
    const route = ROUTES.find((item) => item.hash === hash);
    if (!route) throw new Error("Unknown synthetic route: " + hash);
    await waitForRoute(session, route);
    const metrics = await session.evaluate(metricsScript());
    if (!metrics?.status?.ready || metrics.status.label !== route.label) {
      throw new Error("First-screen data lost on " + hash);
    }
    return { route: hash, ...metrics };
  } catch (error) {
    let pageState = null;
    if (session) {
      try { pageState = await session.evaluate(routeStatusScript()); } catch { /* Chrome may be gone. */ }
    }
    const failure = new Error("Synthetic cold load failed on " + hash);
    failure.diagnosis = classifyColdFailure(error, pageState, apiTrace.snapshot());
    throw failure;
  } finally {
    session?.close();
    await stopChrome(chrome);
    rmSync(profileDir, { recursive: true, force: true, maxRetries: 5, retryDelay: 150 });
  }
}

/** A failed cold load is retried once in a completely new Chrome profile. */
async function probeBrowser(hash) {
  const result = await probeColdWithRetry(
    () => probeBrowserAttempt(hash),
    (failedAttempt) => sleep(failedAttempt?.diagnosis?.category === "rate_limited" ? 8000 : 900),
  );
  if (result.ok) return { ...result.metrics, attempts: result.attempts };
  const error = new Error("Two unsuccessful cold loads on " + hash + ": " +
    result.attempts.map((a) => a.diagnosis.category).join(" / "));
  error.attempts = result.attempts;
  throw error;
}

/** Same browser + cache, measuring user-menu navigation without page reload. */
async function probeSpaNavigationAttempt() {
  const profileDir = mkdtempSync(join(tmpdir(), "otello-prod-spa-perf-"));
  const chrome = spawn(chromeBin, [
    "--headless=new", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
    "--disable-background-networking", "--disable-extensions", "--no-first-run",
    "--window-size=1440,1100", "--remote-debugging-address=127.0.0.1",
    "--remote-debugging-port=0", "--user-data-dir=" + profileDir, "about:blank",
  ], { stdio: ["ignore", "ignore", "pipe"] });
  let stderr = "";
  chrome.stderr.on("data", (data) => { stderr = (stderr + String(data)).slice(-2000); });
  let session = null;
  const apiTrace = createApiDiagnostics(base.origin);
  try {
    const port = await devtoolsPort(profileDir, chrome, () => stderr);
    const response = await fetch("http://127.0.0.1:" + port + "/json/new?about:blank", {
      method: "PUT", signal: AbortSignal.timeout(5000),
    });
    if (!response.ok) throw new Error("Unable to create Chrome tab for SPA");
    const tab = await response.json();
    session = new CdpSession(tab.webSocketDebuggerUrl);
    await session.connect();
    for (const method of [
      "Network.requestWillBeSent", "Network.responseReceived",
      "Network.loadingFailed", "Network.loadingFinished",
    ]) session.on(method, (params) => apiTrace.onEvent(method, params));
    await session.send("Network.enable");
    await session.send("Runtime.enable");
    await session.send("Page.enable");
    await session.send("Page.addScriptToEvaluateOnNewDocument", {
      source: observerInjection(),
    });
    await session.send("Page.navigate", { url: new URL("/#oversikt", base).toString() });
    await waitForRoute(session, ROUTES[0]);
    const result = [];

    for (const route of [...ROUTES.slice(1), ROUTES[0]]) {
      const clicked = await session.evaluate(`(() => {
        const button = [...document.querySelectorAll("button")].find(
          (item) => item.textContent?.trim() === ${JSON.stringify(route.label)}
        );
        if (!button || button.disabled) return false;
        window.__otelloPerfNavigationStart = performance.now();
        window.__otelloSynthetic?.arm(${JSON.stringify(route.hash)}, window.__otelloPerfNavigationStart);
        button.click();
        return true;
      })()`);
      if (!clicked) throw new Error("Navigation button missing: " + route.label);
      await waitForRoute(session, route);
      const metrics = await session.evaluate(metricsScript(true));
      if (!metrics?.status?.ready || metrics.status.label !== route.label) {
        throw new Error("SPA content lost on " + route.hash);
      }
      result.push({
        label: route.label,
        route: route.hash,
        navigationMs: metrics.firstDataMs,
        apiResources: metrics.apiResources,
        scriptResources: metrics.scriptResources,
        longTaskCount: metrics.longTaskCount,
        longTaskTotalMs: metrics.longTaskTotalMs,
        observerCaptured: metrics.observerCaptured,
      });
    }
    return result;
  } catch (error) {
    error.diagnosis = classifyColdFailure(error, null, apiTrace.snapshot());
    throw error;
  } finally {
    session?.close();
    await stopChrome(chrome);
    rmSync(profileDir, { recursive: true, force: true, maxRetries: 5, retryDelay: 150 });
  }
}

function isRateLimitedDiagnosis(diagnosis) {
  return diagnosis?.category === "rate_limited" ||
    Boolean(diagnosis?.apiIssues?.some((item) => item.status === 429));
}

async function probeSpaNavigation() {
  try {
    return { navigation: await probeSpaNavigationAttempt(), recoveredRateLimit: false };
  } catch (initialError) {
    const firstLimited = isRateLimitedDiagnosis(initialError?.diagnosis);
    console.log("SPA navigation retry after transient failure: " +
      (firstLimited ? "rate_limited" : String(initialError).slice(0, 250)));
    await sleep(firstLimited ? 8000 : 1000);
    try {
      return {
        navigation: await probeSpaNavigationAttempt(),
        recoveredRateLimit: firstLimited,
      };
    } catch (retryError) {
      if (isRateLimitedDiagnosis(retryError?.diagnosis)) {
        const limited = new Error("SPA navigation HTTP 429");
        limited.status = 429;
        throw limited;
      }
      throw retryError;
    }
  }
}

async function main() {
  const result = {
    checkedAt: new Date().toISOString(),
    site: base.origin,
    browser: [],
    navigation: [],
    api: [],
    recoveredColdLoads: [],
    coldFailures: [],
    rateLimits: [],
    errors: [],
  };
  for (const endpoint of [
    "/api/health", "/api/dashboard/bootstrap", "/api/dashboard/summary",
    "/api/dashboard/economic", "/api/buybacks/overview-status", "/api/overview/events",
    "/api/dashboard/discount-history?days=365&max_points=72",
    "/api/market/quotes", "/api/buybacks/dashboard", "/api/bemobi/dashboard",
    "/api/bemobi/consensus", "/api/fx/dashboard", "/api/brazil/dashboard",
    "/api/news-events", "/api/dashboard/runtime-status",
  ]) {
    try {
      const measured = await probeApi(endpoint);
      result.api.push(measured);
      if (measured.rateLimitedAttempts) {
        result.rateLimits.push({
          scope: "api", path: new URL(endpoint, base).pathname,
          attempts: measured.rateLimitedAttempts, recovered: true,
        });
      }
    } catch (error) {
      if (isRateLimitError(error)) {
        result.rateLimits.push({
          scope: "api", path: new URL(endpoint, base).pathname,
          attempts: error.rateLimitedAttempts, recovered: false,
        });
      } else {
        result.errors.push(endpoint + ": " + String(error));
      }
    }
  }
  for (const { hash } of ROUTES) {
    // Browser requests share the same production IP rate limit as API probes.
    await sleep(1500);
    try {
      const measured = await probeBrowser(hash);
      result.browser.push(measured);
      if (measured.attempts.length > 1) {
        result.recoveredColdLoads.push({ route: hash, attempts: measured.attempts });
      }
      if (measured.attempts.some((a) => isRateLimitedDiagnosis(a.diagnosis))) {
        result.rateLimits.push({ scope: "cold_load", route: hash, recovered: true });
      }
    } catch (error) {
      const attempts = error.attempts || [];
      result.coldFailures.push({ route: hash, attempts });
      if (attempts.length && attempts.every((a) => isRateLimitedDiagnosis(a.diagnosis))) {
        result.rateLimits.push({ scope: "cold_load", route: hash, recovered: false });
      } else {
        result.errors.push(hash + ": " + String(error));
      }
    }
  }
  await sleep(3000);
  try {
    const spa = await probeSpaNavigation();
    result.navigation = spa.navigation;
    if (spa.recoveredRateLimit) {
      result.rateLimits.push({ scope: "navigation", recovered: true });
    }
  } catch (error) {
    if (isRateLimitError(error)) {
      result.rateLimits.push({ scope: "navigation", recovered: false });
    } else {
      result.errors.push("SPA navigation: " + String(error));
    }
  }
  writeFileSync(reportPath, JSON.stringify(result, null, 2) + "\n");

  function resourceLabel(resource) {
    if (!resource) return "–";
    // Render only same-origin path, no query strings or third-party origins.
    return "`" + resource.path.replace(/\|/g, "") + "` " + resource.durationMs + " ms";
  }
  const outliers = result.browser
    .filter((b) => (b.domToDataMs ?? 0) > 1000)
    .sort((a, b) => b.domToDataMs - a.domToDataMs)
    .slice(0, 5);
  function attemptSummary(attempts) {
    return attempts.map((attempt) => {
      if (attempt.outcome === "success") return "forsøk " + attempt.attempt + ": OK (" + attempt.firstDataMs + " ms)";
      const diagnosis = attempt.diagnosis;
      const api = diagnosis.apiIssues.map((issue) =>
        issue.path + " " + (issue.status ?? issue.category));
      const pending = diagnosis.pendingApiPaths.map((path) => path + " (venter)");
      return "forsøk " + attempt.attempt + ": " + diagnosis.category +
        (api.length || pending.length ? " [" + [...api, ...pending].join(", ") + "]" : "") +
        " (markør=" + diagnosis.page.markerFound + ", laster=" + diagnosis.page.loading +
        ", utilgjengelig=" + diagnosis.page.unavailable + ")";
    }).join("; ");
  }
  const lines = [
    "## OtelloTracker – produksjonsytelse",
    "",
    "Målt " + result.checkedAt + " fra GitHub-runner med fersk Chrome-profil per direkte åpning.",
    "",
    "### Første synlige hoveddata",
    "",
    "| Side | Hoveddata | DOM klar | DOM → data | Tregeste JS | Tregeste API | Lange oppgaver |",
    "| --- | ---: | ---: | ---: | --- | --- | ---: |",
    ...result.browser.map((b) =>
      "| " + (ROUTES.find((route) => route.hash === b.route)?.label || b.route) +
      " | " + b.firstDataMs + " ms | " + (b.domReadyMs ?? "–") + " ms | " +
      (b.domToDataMs == null ? "–" : b.domToDataMs + " ms") +
      " | " + resourceLabel(b.scriptResources?.[0]) +
      " | " + resourceLabel(b.apiResources?.[0]) +
      " | " + (b.longTaskTotalMs ?? "–") + " ms |"
    ),
    "",
    "### Intern navigering (samme nettleserøkt)",
    "",
    "| Side | Hoveddata | Tregeste JS | Tregeste API | Lange oppgaver |",
    "| --- | ---: | --- | --- | ---: |",
    ...result.navigation.map((n) =>
      "| " + n.label + " | " + n.navigationMs + " ms | " +
      resourceLabel(n.scriptResources?.[0]) + " | " +
      resourceLabel(n.apiResources?.[0]) + " | " +
      (n.longTaskTotalMs ?? "–") + " ms |"
    ),
    "",
    "### API – median av tre forespørsler",
    "",
    "| Endepunkt | Headere | Hele svaret | Størrelse | CF-cache (3) |",
    "| --- | ---: | ---: | ---: | --- |",
    ...result.api.map((a) =>
      "| \`" + a.endpoint + "\` | " + a.medianHeadersMs + " ms | " +
      a.medianTotalMs + " ms | " + a.responseBytes + " byte | " +
      (a.cfCacheStatus?.join(" / ") || "–") + " |"
    ),
    "",
    "### Kandidater for nærmere analyse",
    "",
    ...outliers.map((b) =>
      "- **" + (ROUTES.find((route) => route.hash === b.route)?.label || b.route) +
      "**: " + b.domToDataMs + " ms mellom DOM klar og hoveddata; tregeste JS " +
      resourceLabel(b.scriptResources?.[0]) + "; tregeste API " +
      resourceLabel(b.apiResources?.[0]) + "; lange oppgaver " +
      (b.longTaskTotalMs ?? 0) + " ms. Dette er korrelasjoner, ikke bevist årsak."
    ),
    ...(outliers.length ? [] : ["Ingen sider brukte over 1 sekund fra DOM klar til hovedinnhold i denne kjøringen."]),
    "",
    "### Førstegangsinnlasting: nye forsøk og feilkategorier",
    "",
    ...result.recoveredColdLoads.map((item) =>
      "- **GJENOPPRETTET " + item.route + "**: " + attemptSummary(item.attempts) +
      ". Første feil beholdes i JSON-rapporten."),
    ...result.coldFailures.map((item) =>
      "- **VEDVARENDE FEIL " + item.route + "**: " + attemptSummary(item.attempts)),
    ...(result.recoveredColdLoads.length || result.coldFailures.length ? [] :
      ["Ingen feil ved førstegangsinnlasting."]),
    "",
    "### Rate limiting / datakvalitet",
    "",
    ...result.rateLimits.map((item) =>
      "- HTTP 429: " + item.scope + " " + (item.path || item.route || "") +
      " (" + (item.recovered ? "gjenopprettet" : "ikke gjenopprettet") + ")" +
      (item.attempts ? ", " + item.attempts + " avviste forsøk" : "")),
    ...(result.rateLimits.length ? [
      "Rate-limit-påvirkede kjøringer utelates fra trendmedianer; ventetid regnes ikke som API-latenstid.",
    ] : ["Ingen rate limiting registrert."]),
    "",
    "### Diagnose",
    "",
    ...result.errors.map((e) => "- FEIL: " + e),
    ...(result.errors.length ? [] : ["Ingen feil ved de syntetiske kontrollene."]),
    "",
    "Målingene er syntetiske og representerer ikke reelle brukeres nettverk eller en statistisk P95.",
    "Forespørselstider inkluderer nettverk, Cloudflare og eventuell cache, og er ikke ren Worker-CPU-tid.",
    "JS-ressurstider er nettverksvarighet, IKKE JavaScript-eksekvering. Lange oppgaver er bare oppgaver over 50 ms.",
    "DOM → data måler intervallet fra DOMContentLoaded til første animasjonsramme med hovedinnhold; negativ tid avrundes til null.",
    "CF-cache er bare HTTP-header observert av Node; fravær betyr ikke automatisk cachemiss.",
  ];
  const summary = lines.join("\n") + "\n";
  console.log(summary);
  if (process.env.GITHUB_STEP_SUMMARY) appendFileSync(process.env.GITHUB_STEP_SUMMARY, summary);
  for (const item of result.recoveredColdLoads) {
    console.log("::warning::Førsteinnlasting feilet, men nytt Chrome-forsøk lyktes for " +
      item.route + ": " + attemptSummary(item.attempts));
  }
  if (result.rateLimits.length) {
    console.log("::warning::Ytelsesmålingen ble påvirket av HTTP 429; " +
      "rapporten er ufullstendig og ekskluderes fra trendberegningen.");
  }
  if (result.errors.length) {
    process.stderr.write("Performance monitor failed: " + result.errors.join(" | ") + "\n");
    process.exitCode = 1;
  } else {
    for (const item of result.browser) {
      if (item.firstDataMs > 5000) console.log("::warning::Sakte førsteside " + item.route + ": " + item.firstDataMs + " ms");
    }
    for (const item of result.navigation) {
      if (item.navigationMs > 3000) console.log("::warning::Tregt sideskifte " + item.route + ": " + item.navigationMs + " ms");
    }
  }
}

await main();

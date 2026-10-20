/**
 * Production-only synthetic monitoring. No client telemetry or UI dependencies.
 * Runs in GitHub Actions with a fresh headless Chrome profile per route.
 */
import { spawn } from "node:child_process";
import { appendFileSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { performance } from "node:perf_hooks";
import { classifyColdFailure, createApiDiagnostics, probeColdWithRetry } from "./performance-diagnostics.mjs";

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
async function probeApi(path) {
  const samples = [];
  for (let i = 0; i < 3; i++) {
    const started = performance.now();
    const response = await fetch(new URL(path, base), {
      signal: AbortSignal.timeout(20000),
      headers: { accept: "application/json" },
    });
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
    medianHeadersMs: median(samples.map((s) => s.headersMs)),
    medianTotalMs: median(samples.map((s) => s.totalMs)),
    maxTotalMs: Math.max(...samples.map((s) => s.totalMs)),
    responseBytes: samples.at(-1).bytes,
    cfCacheStatus: samples.map((sample) => sample.cfCacheStatus),
    ageSeconds: samples.map((sample) => sample.ageSeconds),
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

async function probeBrowser(hash) {
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
  try {
    const port = await devtoolsPort(profileDir, chrome, () => stderr);
    const response = await fetch("http://127.0.0.1:" + port + "/json/new?about:blank", {
      method: "PUT", signal: AbortSignal.timeout(5000),
    });
    if (!response.ok) throw new Error("Unable to create Chrome tab");
    const tab = await response.json();
    session = new CdpSession(tab.webSocketDebuggerUrl);
    await session.connect();
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
  } finally {
    session?.close();
    await stopChrome(chrome);
    rmSync(profileDir, { recursive: true, force: true, maxRetries: 5, retryDelay: 150 });
  }
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
  try {
    const port = await devtoolsPort(profileDir, chrome, () => stderr);
    const response = await fetch("http://127.0.0.1:" + port + "/json/new?about:blank", {
      method: "PUT", signal: AbortSignal.timeout(5000),
    });
    if (!response.ok) throw new Error("Unable to create Chrome tab for SPA");
    const tab = await response.json();
    session = new CdpSession(tab.webSocketDebuggerUrl);
    await session.connect();
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
  } finally {
    session?.close();
    await stopChrome(chrome);
    rmSync(profileDir, { recursive: true, force: true, maxRetries: 5, retryDelay: 150 });
  }
}

async function probeSpaNavigation() {
  try {
    return await probeSpaNavigationAttempt();
  } catch (initialError) {
    // One failed cold SPA session can reflect a transient browser / cache race.
    // Retry the full menu walk in a new profile; persistent errors still fail.
    console.log("SPA navigation retry after transient failure: " + String(initialError).slice(0, 500));
    await sleep(1000);
    return probeSpaNavigationAttempt();
  }
}

async function main() {
  const result = {
    checkedAt: new Date().toISOString(),
    site: base.origin,
    browser: [],
    navigation: [],
    api: [],
    errors: [],
  };
  for (const endpoint of [
    "/api/health", "/api/dashboard/bootstrap", "/api/dashboard/economic",
    "/api/dashboard/discount-history?days=365&max_points=72",
    "/api/market/quotes", "/api/buybacks/dashboard", "/api/bemobi/dashboard",
    "/api/bemobi/consensus", "/api/fx/dashboard", "/api/brazil/dashboard",
    "/api/news-events", "/api/dashboard/runtime-status",
  ]) {
    try {
      result.api.push(await probeApi(endpoint));
    } catch (error) {
      result.errors.push(endpoint + ": " + String(error));
    }
  }
  for (const { hash } of ROUTES) {
    try {
      result.browser.push(await probeBrowser(hash));
    } catch (error) {
      result.errors.push(hash + ": " + String(error));
    }
  }
  try {
    result.navigation = await probeSpaNavigation();
  } catch (error) {
    result.errors.push("SPA navigation: " + String(error));
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

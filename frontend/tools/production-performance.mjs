/**
 * Production-only synthetic monitoring. No client telemetry or UI dependencies.
 * Runs in GitHub Actions with a fresh headless Chrome profile per route.
 */
import { spawn } from "node:child_process";
import { appendFileSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { performance } from "node:perf_hooks";

const base = new URL(process.env.OTELLO_SITE_URL || "https://otellotracker.com/");
const chromeBin = process.env.CHROME_BIN || "google-chrome";
const reportPath = process.env.PERF_REPORT_PATH || "performance-report.json";
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

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
    samples.push({ headersMs, totalMs, bytes, status: response.status });
  }
  return {
    endpoint: path,
    medianHeadersMs: median(samples.map((s) => s.headersMs)),
    medianTotalMs: median(samples.map((s) => s.totalMs)),
    maxTotalMs: Math.max(...samples.map((s) => s.totalMs)),
    responseBytes: samples.at(-1).bytes,
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
  }
  async connect() {
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("CDP socket timeout")), 10000);
      this.ws.addEventListener("open", () => { clearTimeout(timer); resolve(); }, { once: true });
      this.ws.addEventListener("error", () => { clearTimeout(timer); reject(new Error("CDP connection failed")); }, { once: true });
    });
    this.ws.addEventListener("message", (event) => {
      const message = JSON.parse(event.data);
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
  const isOverview = location.hash === "#oversikt";
  const isBrazil = location.hash === "#brasil";
  const navText = document.querySelector(".overviewNavCard h2")?.textContent?.trim() || "";
  const brazilReady = Boolean(
    document.querySelector(".brazilInvestorHero") &&
    document.querySelector(".brazilDriverGrid")
  );
  const error = Boolean(document.querySelector(".brazilError")) ||
    document.body.innerText.includes("Kunne ikke hente investordata.");
  const ready = isOverview
    ? /^\d/.test(navText) && navText.includes("kr")
    : isBrazil && brazilReady;
  return { ready, error, navText };
}

function extractBrowserMetrics() {
  const nav = performance.getEntriesByType("navigation")[0];
  const res = performance.getEntriesByType("resource")
    .filter((entry) => {
      try {
        const url = new URL(entry.name);
        return url.origin === location.origin && url.pathname.startsWith("/api/");
      } catch {
        return false;
      }
    })
    .map((entry) => ({
      path: new URL(entry.name).pathname,
      durationMs: Math.round(entry.duration),
    }))
    .sort((a, b) => b.durationMs - a.durationMs)
    .slice(0, 5);
  return {
    firstDataMs: Math.round(performance.now()),
    documentTtfbMs: nav ? Math.round(nav.responseStart) : null,
    domReadyMs: nav ? Math.round(nav.domContentLoadedEventEnd) : null,
    apiResources: res,
    status: screenState(),
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
    const pageUrl = new URL("/" + hash, base).toString();
    await session.send("Page.navigate", { url: pageUrl });
    const deadline = Date.now() + 25000;
    let finalState;
    while (Date.now() < deadline) {
      finalState = await session.evaluate("(" + screenState.toString() + ")()");
      if (finalState?.error) throw new Error("Investor data error on " + hash);
      if (finalState?.ready) break;
      await sleep(120);
    }
    if (!finalState?.ready) throw new Error("No first-screen data after 25s on " + hash);
    const metrics = await session.evaluate(
      "(async () => { await new Promise(resolve => requestAnimationFrame(resolve)); " +
      "const screenState = (" + screenState.toString() + "); " +
      "return (" + extractBrowserMetrics.toString() + ")(); })()"
    );
    if (!metrics?.status?.ready) throw new Error("First screen lost valid data on " + hash);
    return { route: hash, ...metrics };
  } finally {
    session?.close();
    await stopChrome(chrome);
    rmSync(profileDir, { recursive: true, force: true, maxRetries: 5, retryDelay: 150 });
  }
}

async function main() {
  const result = {
    checkedAt: new Date().toISOString(),
    site: base.origin,
    browser: [],
    api: [],
    errors: [],
  };
  for (const endpoint of [
    "/api/health", "/api/dashboard/bootstrap", "/api/dashboard/economic", "/api/brazil/dashboard",
  ]) {
    try {
      result.api.push(await probeApi(endpoint));
    } catch (error) {
      result.errors.push(endpoint + ": " + String(error));
    }
  }
  for (const hash of ["#oversikt", "#brasil"]) {
    try {
      result.browser.push(await probeBrowser(hash));
    } catch (error) {
      result.errors.push(hash + ": " + String(error));
    }
  }
  writeFileSync(reportPath, JSON.stringify(result, null, 2) + "\n");

  const lines = [
    "## OtelloTracker – produksjonsytelse",
    "",
    "Målt " + result.checkedAt + " fra GitHub-runner med fersk Chrome-profil per side.",
    "",
    "### Første synlige hoveddata",
    "",
    "| Side | Tid | Dokument-TTFB | DOM klar |",
    "| --- | ---: | ---: | ---: |",
    ...result.browser.map((b) =>
      "| " + b.route + " | " + b.firstDataMs + " ms | " +
      (b.documentTtfbMs ?? "–") + " ms | " + (b.domReadyMs ?? "–") + " ms |"
    ),
    "",
    "### API – median av tre forespørsler",
    "",
    "| Endepunkt | Til responsheadere | Hele svaret | Størrelse |",
    "| --- | ---: | ---: | ---: |",
    ...result.api.map((a) =>
      "| \`" + a.endpoint + "\` | " + a.medianHeadersMs + " ms | " +
      a.medianTotalMs + " ms | " + a.responseBytes + " byte |"
    ),
    "",
    "### Diagnose",
    "",
    ...result.errors.map((e) => "- FEIL: " + e),
    ...(result.errors.length ? [] : ["Ingen feil ved de syntetiske kontrollene."]),
    "",
    "Målingene er syntetiske og representerer ikke reelle brukeres nettverk eller en statistisk P95.",
    "Forespørselstider inkluderer nettverk, Cloudflare og eventuell cache, og er ikke ren Worker-CPU-tid.",
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
  }
}

await main();

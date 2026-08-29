import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const baseUrl = process.argv[2] ?? "http://127.0.0.1:8787/";
const chromeBin = process.env.CHROME_BIN ?? "google-chrome";
const configuredDebugPort = Number(process.env.CHROME_DEBUG_PORT ?? 9222);
if (!Number.isInteger(configuredDebugPort) || configuredDebugPort < 0 || configuredDebugPort > 65535) {
  throw new Error(`Ugyldig CHROME_DEBUG_PORT: ${process.env.CHROME_DEBUG_PORT}`);
}
const profileDir = mkdtempSync(join(tmpdir(), "otello-browser-smoke-"));
const chrome = spawn(
  chromeBin,
  [
    "--headless=new",
    "--no-sandbox",
    "--disable-gpu",
    "--disable-dev-shm-usage",
    "--disable-background-networking",
    "--disable-default-apps",
    "--disable-extensions",
    "--disable-sync",
    "--no-first-run",
    "--no-default-browser-check",
    "--window-size=1440,1200",
    "--remote-debugging-address=127.0.0.1",
    `--remote-debugging-port=${configuredDebugPort}`,
    `--user-data-dir=${profileDir}`,
    "about:blank"
  ],
  { stdio: ["ignore", "ignore", "pipe"] }
);

let chromeStderr = "";
chrome.stderr.on("data", (chunk) => {
  chromeStderr += chunk.toString();
  if (chromeStderr.length > 12000) chromeStderr = chromeStderr.slice(-12000);
});

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function stopChrome() {
  if (chrome.exitCode !== null || chrome.signalCode !== null) return;

  chrome.kill("SIGTERM");
  let deadline = Date.now() + 3000;
  while (chrome.exitCode === null && chrome.signalCode === null && Date.now() < deadline) {
    await sleep(50);
  }

  if (chrome.exitCode === null && chrome.signalCode === null) {
    chrome.kill("SIGKILL");
    deadline = Date.now() + 1000;
    while (chrome.exitCode === null && chrome.signalCode === null && Date.now() < deadline) {
      await sleep(50);
    }
  }
}

async function jsonFetch(url, init) {
  const response = await fetch(url, init);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}: ${url}`);
  return response.json();
}

function discoverDebugPort() {
  if (configuredDebugPort > 0) return configuredDebugPort;

  try {
    const activePort = readFileSync(join(profileDir, "DevToolsActivePort"), "utf8");
    const [portLine] = activePort.trim().split(/\r?\n/);
    const port = Number(portLine);
    if (Number.isInteger(port) && port > 0 && port <= 65535) return port;
  } catch (error) {
    if (error?.code !== "ENOENT") {
      chromeStderr += `\nKunne ikke lese DevToolsActivePort: ${error}`;
    }
  }
  return null;
}

async function waitForDevtools() {
  const deadline = Date.now() + 20000;
  while (Date.now() < deadline) {
    if (chrome.exitCode !== null || chrome.signalCode !== null) {
      throw new Error(
        `Chrome avsluttet før DevTools startet (exit=${chrome.exitCode}, signal=${chrome.signalCode}).\n${chromeStderr}`
      );
    }

    const debugPort = discoverDebugPort();
    if (debugPort) {
      try {
        await jsonFetch(`http://127.0.0.1:${debugPort}/json/version`);
        return debugPort;
      } catch {
        // Chrome may have written DevToolsActivePort just before the endpoint is ready.
      }
    }
    await sleep(200);
  }
  throw new Error(`Chrome DevTools startet ikke.\n${chromeStderr}`);
}

class CdpSession {
  constructor(url) {
    this.url = url;
    this.nextId = 1;
    this.pending = new Map();
    this.ws = null;
  }

  async connect() {
    this.ws = new WebSocket(this.url);
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("CDP WebSocket timeout")), 10000);
      this.ws.addEventListener("open", () => {
        clearTimeout(timer);
        resolve();
      }, { once: true });
      this.ws.addEventListener("error", (event) => {
        clearTimeout(timer);
        reject(event.error ?? new Error("CDP WebSocket error"));
      }, { once: true });
    });
    this.ws.addEventListener("message", (event) => {
      const message = JSON.parse(event.data);
      if (!message.id) return;
      const pending = this.pending.get(message.id);
      if (!pending) return;
      this.pending.delete(message.id);
      if (message.error) pending.reject(new Error(JSON.stringify(message.error)));
      else pending.resolve(message.result ?? {});
    });
  }

  send(method, params = {}) {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }

  async evaluate(expression) {
    const result = await this.send("Runtime.evaluate", {
      expression,
      awaitPromise: true,
      returnByValue: true
    });
    if (result.exceptionDetails) {
      throw new Error(`Browser evaluation failed: ${JSON.stringify(result.exceptionDetails)}`);
    }
    return result.result?.value;
  }

  close() {
    this.ws?.close();
  }
}

async function waitFor(session, expression, label, timeoutMs = 15000) {
  const deadline = Date.now() + timeoutMs;
  let lastValue;
  while (Date.now() < deadline) {
    lastValue = await session.evaluate(expression);
    if (lastValue) return lastValue;
    await sleep(150);
  }
  const body = await session.evaluate("document.body?.innerText?.slice(0, 6000) ?? ''");
  throw new Error(`Timeout mens browser-smoke ventet på ${label}. Siste verdi: ${JSON.stringify(lastValue)}\n${body}`);
}

async function clickView(session, label, heading, readySelector) {
  const clicked = await session.evaluate(`(() => {
    const button = [...document.querySelectorAll('button')].find((item) => item.textContent.trim() === ${JSON.stringify(label)});
    if (!button || button.disabled) return false;
    button.click();
    return true;
  })()`);
  if (!clicked) throw new Error(`Fant ikke aktiv navigasjonsknapp: ${label}`);

  await waitFor(
    session,
    `document.querySelector('h1')?.textContent?.trim() === ${JSON.stringify(heading)}`,
    `overskrift for ${label}`
  );
  await waitFor(
    session,
    `Boolean(document.querySelector(${JSON.stringify(readySelector)}))`,
    `ferdig investorvisning ${label}`
  );

  const body = await session.evaluate("document.body.innerText");
  for (const errorText of [
    "Kunne ikke hente investordata.",
    "Kunne ikke hente historikkdata.",
    "Kunne ikke hente tilbakekjøpsdata.",
    "Kunne ikke hente Bemobi-data.",
    "Kunne ikke hente konsensusdata.",
    "Kunne ikke hente NAV-sammensetningen.",
    "Kunne ikke hente NAV-historikk."
  ]) {
    if (body.includes(errorText)) throw new Error(`${label} viser feiltilstand: ${errorText}`);
  }
}

async function main() {
  const debugPort = await waitForDevtools();
  const page = await jsonFetch(
    `http://127.0.0.1:${debugPort}/json/new?${encodeURIComponent(baseUrl)}`,
    { method: "PUT" }
  );
  const session = new CdpSession(page.webSocketDebuggerUrl);
  await session.connect();
  await session.send("Runtime.enable");
  await session.send("Page.enable");

  await waitFor(
    session,
    "document.readyState === 'complete' && document.querySelector('.overviewV2 .estimatedHero h2')?.textContent?.includes('kr')",
    "vellykket innlasting av NAV"
  );

  const overviewLabels = await session.evaluate(`(() => ({
    body: document.body.innerText,
    topbar: document.querySelector('.investorTopbar')?.innerText ?? '',
    kpis: [...document.querySelectorAll('.overviewKpiGrid .label')].map((item) => item.textContent?.trim())
  }))()`);
  if (overviewLabels.body.includes("OTELLO / BEMOBI") || overviewLabels.body.includes("ESTIMERT NAV")) {
    throw new Error(`Gamle globale NAV-etiketter er fortsatt synlige: ${JSON.stringify(overviewLabels)}`);
  }
  if (!overviewLabels.kpis.includes("BRL/NOK") || overviewLabels.kpis.includes("OTEC-kurs")) {
    throw new Error(`Oversiktskortene er ikke oppdatert: ${JSON.stringify(overviewLabels.kpis)}`);
  }

  const accessibility = await session.evaluate(`(() => ({
    skipTarget: document.querySelector('.skipLink')?.getAttribute('href'),
    mainFocusable: document.querySelector('#main-content')?.getAttribute('tabindex'),
    activePage: document.querySelector('[aria-current="page"]')?.textContent?.trim()
  }))()`);
  if (accessibility.skipTarget !== "#main-content" || accessibility.mainFocusable !== "-1") {
    throw new Error(`Hoppelenken peker ikke til fokuserbart hovedinnhold: ${JSON.stringify(accessibility)}`);
  }
  if (accessibility.activePage !== "Oversikt") {
    throw new Error(`Aktiv meny er ikke tilgjengelig markert: ${JSON.stringify(accessibility)}`);
  }

  await session.send("Emulation.setDeviceMetricsOverride", {
    width: 390,
    height: 844,
    deviceScaleFactor: 1,
    mobile: true
  });
  const mobileNavigationVisible = await session.evaluate(`(() => {
    const navigation = document.querySelector('.sidebar nav');
    return navigation && getComputedStyle(navigation).display !== 'none' && navigation.getBoundingClientRect().height > 0;
  })()`);
  if (!mobileNavigationVisible) throw new Error("Hovedmenyen er skjult på mobil.");
  await session.send("Emulation.clearDeviceMetricsOverride");

  await clickView(session, "Oversikt", "Otello investoroversikt", ".overviewGrid");
  await clickView(session, "NAV", "NAV", ".compositionTable");
  const navRoute = await session.evaluate("({ hash: location.hash, title: document.title })");
  if (navRoute.hash !== "#nav" || navRoute.title !== "NAV | Otello") {
    throw new Error(`NAV-rute eller sidetittel er feil: ${JSON.stringify(navRoute)}`);
  }
  await clickView(session, "Historikk", "Historisk NAV-rabatt", ".historyAxisCard");
  await clickView(session, "Tilbakekjøpsprogram", "Tilbakekjøpsprogram", ".buybackPage");
  await clickView(session, "Bemobi", "Bemobi", ".bemobiPage");
  await clickView(session, "Konsensus", "Konsensus", ".consensusPage");
  await clickView(session, "Nyheter", "Nyheter og hendelser", ".newsEventsPage");
  await clickView(session, "Datakvalitet", "Datakvalitet", ".dataQualityPage");

  console.log("Browser-smoke bestått for Oversikt, NAV, Historikk, Tilbakekjøpsprogram, Bemobi, Konsensus, Nyheter og Datakvalitet.");
  session.close();
}

try {
  await main();
} finally {
  await stopChrome();
  try {
    rmSync(profileDir, {
      recursive: true,
      force: true,
      maxRetries: 8,
      retryDelay: 100
    });
  } catch (error) {
    if (["ENOTEMPTY", "EBUSY", "EPERM"].includes(error?.code)) {
      console.warn(`Kunne ikke rydde midlertidig Chrome-profil ${profileDir}: ${error.code}`);
    } else {
      throw error;
    }
  }
}

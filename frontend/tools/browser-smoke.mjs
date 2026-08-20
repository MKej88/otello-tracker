import { spawn } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const baseUrl = process.argv[2] ?? "http://127.0.0.1:8787/";
const chromeBin = process.env.CHROME_BIN ?? "google-chrome";
const debugPort = Number(process.env.CHROME_DEBUG_PORT ?? 9222);
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
    `--remote-debugging-port=${debugPort}`,
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

async function jsonFetch(url, init) {
  const response = await fetch(url, init);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}: ${url}`);
  return response.json();
}

async function waitForDevtools() {
  const deadline = Date.now() + 20000;
  while (Date.now() < deadline) {
    try {
      return await jsonFetch(`http://127.0.0.1:${debugPort}/json/version`);
    } catch {
      await sleep(200);
    }
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
    "Kunne ikke hente tilbakekjøpsdata.",
    "Kunne ikke hente Bemobi-data.",
    "Kunne ikke hente konsensusdata."
  ]) {
    if (body.includes(errorText)) throw new Error(`${label} viser feiltilstand: ${errorText}`);
  }
}

async function main() {
  await waitForDevtools();
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
    "document.readyState === 'complete' && document.body?.innerText?.includes('API tilkoblet')",
    "vellykket API-tilkobling"
  );

  const disabledViewsOk = await session.evaluate(`['Historikk', 'Nyheter', 'Innstillinger'].every((label) => {
    const button = [...document.querySelectorAll('button')].find((item) => item.textContent.trim() === label);
    return Boolean(button?.disabled);
  })`);
  if (!disabledViewsOk) throw new Error("En inaktiv menyvisning er blitt klikkbar uten browser-smoke-dekning.");

  await clickView(session, "Oversikt", "Otello investoroversikt", ".overviewGrid");
  await clickView(session, "NAV", "NAV og verdsettelse", ".navCompositionGrid");
  await clickView(session, "Tilbakekjøp", "Tilbakekjøp", ".buybackPage");
  await clickView(session, "Bemobi", "Bemobi", ".bemobiPage");
  await clickView(session, "Konsensus", "Konsensus", ".consensusPage");

  console.log("Browser-smoke bestått for Oversikt, NAV, Tilbakekjøp, Bemobi og Konsensus.");
  session.close();
}

try {
  await main();
} finally {
  chrome.kill("SIGTERM");
  await sleep(100);
  rmSync(profileDir, { recursive: true, force: true });
}

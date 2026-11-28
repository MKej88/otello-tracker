import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fixtureOrigin, fixtureScript, HISTORY_PATH, BUYBACK_PATH, BRAZIL_PATH, BUYBACK_FIXTURE_DATE } from "./browser-data-fixtures.mjs";

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

// A successful HTTP response may explicitly say that a financial dataset
// is unavailable. Test that exact state, never a generic loading/error screen.
async function datasetSelector(baseUrl, path, name, readySelector, emptySelector, classify) {
  const payload = await jsonFetch(new URL(path, baseUrl));
  const ready = classify(payload);
  if (typeof ready !== "boolean") {
    throw new Error(`${name}: API mangler entydig datastatus.`);
  }
  if (!ready) console.log(`${name}: API bekrefter manglende datagrunnlag; kontrollerer tomtilstand (ikke full datavisning).`);
  return ready ? readySelector : emptySelector;
}

function explicitReady(payload) {
  return typeof payload?.ready === "boolean" ? payload.ready : undefined;
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

async function checkRichMobileViews(session) {
  // A real historical Worker response was already compared with SQLite in CI.
  // Replay that response plus two explicitly synthetic UI payloads only in a
  // fresh local test document, leaving the ordinary real-API smoke intact.
  fixtureOrigin(baseUrl);
  const buyback = await jsonFetch(new URL(BUYBACK_PATH + "?as_of_date=" + BUYBACK_FIXTURE_DATE, baseUrl));
  const script = await session.send("Page.addScriptToEvaluateOnNewDocument", {
    source: fixtureScript(baseUrl, buyback),
  });
  try {
    await session.send("Page.reload", {ignoreCache:true});
    await waitFor(session, "Boolean(window.__otelloTestFixtureHits) && document.readyState === 'complete'", "lokalt datarikt testdokument");
    const richViews = [
      ["historikk", "Historisk NAV-rabatt", HISTORY_PATH, ".historyAxisCard svg", ".historyKpiGrid .historyKpi", 4],
      ["tilbakekjop", "Tilbakekjøpsprogram", BUYBACK_PATH, ".buybackHero", ".buybackKpis .buybackKpi", 3],
      ["brasil", "Brasil", BRAZIL_PATH, ".brazilChangeTable", ".brazilDriverGrid .brazilDriverCard", 3],
    ];
    const failures = [];
    for (const width of [390, 320, 768]) {
      await session.send("Emulation.setDeviceMetricsOverride", {width,height:844,deviceScaleFactor:1,mobile:true});
      for (const [slug, heading, path, selector, cards, count] of richViews) {
        await session.evaluate("location.hash = " + JSON.stringify("#" + slug));
        await waitFor(session, `document.querySelector('h1')?.textContent?.trim() === ${JSON.stringify(heading)} &&
          Boolean(document.querySelector(${JSON.stringify(selector)})) &&
          document.querySelectorAll(${JSON.stringify(cards)}).length === ${count} &&
          window.__otelloTestFixtureHits?.[${JSON.stringify(path)}] > 0`, `datarik ${heading} ved ${width}px`);
        if (slug === "brasil") {
          await session.evaluate("document.querySelectorAll('.brazilDetailBlock').forEach(el => el.open = true)");
          await waitFor(session, "document.querySelectorAll('.brazilDetailMetric').length === 5", "fem utfylte Brasil-indikatorer");
        }
        await session.evaluate("new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))");
        const dimensions = await session.evaluate(`(() => ({
          viewport: document.documentElement.clientWidth,
          html: document.documentElement.scrollWidth,
          body: document.body.scrollWidth,
          main: Math.round(document.querySelector('.investorMainV2')?.getBoundingClientRect().width ?? 0)
        }))()`);
        if (Math.abs(dimensions.viewport-width)>2 || dimensions.main<=0 || dimensions.html>width+2 || dimensions.body>width+2 || dimensions.main>width+2) {
          failures.push(`Datarik mobil-overflyt ${slug} ${width}px ${JSON.stringify(dimensions)}`);
          console.error(failures.at(-1));
        } else {
          console.log(`Datarik mobil OK: ${slug} ${width}px ${JSON.stringify(dimensions)}`);
        }
      }
    }
    if (failures.length) throw new Error(failures.join("\\n"));
    console.log("Datarik mobilkontroll bestått: 9/9 kombinasjoner.");
  } finally {
    await session.send("Emulation.clearDeviceMetricsOverride");
    await session.send("Page.removeScriptToEvaluateOnNewDocument", {identifier:script.identifier});
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
    "document.readyState === 'complete' && document.querySelector('.overviewV3 .overviewNavCardV3 h2')?.textContent?.includes('kr')",
    "vellykket innlasting av NAV"
  );

  const overviewLabels = await session.evaluate(`(() => ({
    topbar: document.querySelector('.investorTopbar')?.innerText ?? '',
    kpis: [...document.querySelectorAll('.overviewDriverGrid .overviewDriverCard .label')].map((item) => item.textContent?.trim())
  }))()`);
  if (overviewLabels.topbar.includes("OTELLO / BEMOBI") || overviewLabels.topbar.includes("ESTIMERT NAV")) {
    throw new Error(`Gamle globale NAV-etiketter er fortsatt synlige: ${JSON.stringify(overviewLabels)}`);
  }
  if (["BEMOBI", "BRL/NOK", "TILBAKEKJØP"].some((label) => !overviewLabels.kpis.includes(label))) {
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
    const button = document.querySelector('.mobileMenuButton');
    const desktop = document.querySelector('.desktopSidebar');
    return button && button.getBoundingClientRect().height > 0
      && getComputedStyle(button).display !== 'none'
      && desktop && getComputedStyle(desktop).display === 'none';
  })()`);
  if (!mobileNavigationVisible) throw new Error("Mobilmeny-knappen er skjult eller desktopmenyen er synlig på mobil.");
  await session.evaluate("document.querySelector('.mobileMenuButton')?.click()");
  await waitFor(
    session,
    "Boolean(document.querySelector('.mobileMenuPanel')) && document.querySelectorAll('.mobileMenuPanel .navItem').length === 12",
    "alle tolv sider i mobilmenyen"
  );
  await session.evaluate("document.querySelector('.mobileMenuClose')?.click()");
  await waitFor(session, "!document.querySelector('.mobileMenuPanel')", "lukket mobilmeny");
  await session.send("Emulation.clearDeviceMetricsOverride");

  await clickView(session, "Oversikt", "Otello investoroversikt", ".overviewHeroGrid");
  await clickView(session, "NAV", "NAV", ".compositionTable");
  const navRoute = await session.evaluate("({ hash: location.hash, title: document.title })");
  if (navRoute.hash !== "#nav" || navRoute.title !== "NAV | Otello") {
    throw new Error(`NAV-rute eller sidetittel er feil: ${JSON.stringify(navRoute)}`);
  }
  // The deterministic fixture may legitimately have no eligible estimated
  // history. Verify the exact UI request, rather than requiring a chart for
  // data that the API explicitly reports unavailable.
  const historyPayload = await jsonFetch(new URL("/api/dashboard/discount-history?days=365&max_points=72", baseUrl));
  const history = historyPayload.estimated;
  if (typeof history?.ready !== "boolean" || (history.ready && !history.statistics)) {
    throw new Error("Historikk-API mangler gyldig estimert historikkstatus.");
  }
  const historyReadySelector = history.ready
    ? ".historyV2 .historyAxisCard"
    : ".historyV2 .resourceNotice.empty";
  await clickView(session, "Historikk", "Historisk NAV-rabatt", historyReadySelector);
  if (!history.ready) {
    const emptyNotice = await session.evaluate("document.querySelector('.historyV2 .resourceNotice.empty')?.textContent");
    if (!emptyNotice?.includes("ikke nok kildebelagt historikk")) {
      throw new Error("Historikkens tomtilstand samsvarer ikke med API.");
    }
    console.log("Historikk: API bekrefter utilstrekkelig datagrunnlag; tomtilstand kontrollert (ikke graf).");
  }
  const buybackSelector = await datasetSelector(baseUrl, "/api/buybacks/dashboard",
    "Tilbakekjøpsprogram", ".buybackPage", ".buybackNotice",
    (payload) => payload?.ready === true ? true
      : payload?.ready === false && payload.status === "NO_ACTIVE_PROGRAM" ? false : undefined);
  const bemobiSelector = await datasetSelector(baseUrl, "/api/bemobi/dashboard",
    "Bemobi", ".bemobiPage", ".bemobiNotice", explicitReady);
  const consensusSelector = await datasetSelector(baseUrl, "/api/bemobi/consensus",
    "Konsensus", ".consensusPage", ".consensusNotice", explicitReady);
  const fxSelector = await datasetSelector(baseUrl, "/api/fx/dashboard",
    "BRL/NOK", ".fxPage", ".fxError", explicitReady);
  const brazilSelector = await datasetSelector(baseUrl, "/api/brazil/dashboard",
    "Brasil", ".brazilPage", ".brazilError", (payload) =>
      payload?.snapshot_unavailable === true ? false
        : payload && typeof payload === "object" && !Array.isArray(payload) && payload.as_of_date ? true : undefined);
  await clickView(session, "Tilbakekjøpsprogram", "Tilbakekjøpsprogram", buybackSelector);
  if (buybackSelector === ".buybackNotice") {
    const notice = await session.evaluate("document.querySelector('.buybackNotice')?.textContent");
    if (!notice?.includes("NO_ACTIVE_PROGRAM")) throw new Error("Tilbakekjøpsstatus samsvarer ikke med API.");
  }
  await clickView(session, "Bemobi", "Bemobi", bemobiSelector);
  await clickView(session, "Konsensus", "Konsensus", consensusSelector);
  await clickView(session, "Nyheter", "Nyheter og hendelser", ".newsEventsPage");
  await clickView(session, "Datakvalitet", "Datakvalitet", ".dataQualityPage");

  // Check all twelve investor routes at narrow phone and tablet widths.
  // Scrollable data tables are permitted, but the page itself must not overflow.
  const mobileViews = [
    ["oversikt","Otello investoroversikt",".overviewV3"],
    ["nav","NAV",".navV2 .compositionTable"],
    ["nav-sensitivitet","NAV-sensitivitet",".sensitivityPage"],
    ["historikk","Historisk NAV-rabatt",historyReadySelector],
    ["tilbakekjop","Tilbakekjøpsprogram",buybackSelector],
    ["cash","Cash & kapitalallokering",".cashPage"],
    ["bemobi","Bemobi",bemobiSelector],
    ["brl-nok","BRL/NOK",fxSelector],
    ["brasil","Brasil",brazilSelector],
    ["konsensus","Konsensus",consensusSelector],
    ["nyheter","Nyheter og hendelser",".newsEventsPage"],
    ["datakvalitet","Datakvalitet",".dataQualityPage"],
  ];
  const mobileLayoutFailures = [];
  for (const width of [390, 320, 768]) {
    await session.send("Emulation.setDeviceMetricsOverride", {
      width, height: 844, deviceScaleFactor: 1, mobile: true
    });
    for (const [slug, heading, readySelector] of mobileViews) {
      await session.evaluate(`location.hash = ${JSON.stringify("#" + slug)}`);
      await waitFor(
        session,
        `document.querySelector('h1')?.textContent?.trim() === ${JSON.stringify(heading)}`,
        `mobilrute ${heading} ved ${width}px`
      );
      await waitFor(
        session,
        `Boolean(document.querySelector(${JSON.stringify(readySelector)})) && !document.querySelector('.loadingPlaceholderPage')`,
        `ferdig mobilvisning ${heading} ved ${width}px`
      );
      if (slug === "tilbakekjop" && buybackSelector === ".buybackNotice") {
        const notice = await session.evaluate("document.querySelector(\'.buybackNotice\')?.textContent");
        if (!notice?.includes("NO_ACTIVE_PROGRAM")) throw new Error(`Tilbakekjøpsstatus samsvarer ikke med API ved ${width}px.`);
      }
      if (slug === "historikk") {
        const historyError = await session.evaluate("Boolean(document.querySelector(\'.historyV2 .resourceNotice.error\'))");
        if (historyError) throw new Error(`Historikk viser innlastingsfeil ved ${width}px.`);
      }
      const dimensions = await session.evaluate(`(() => ({
        viewport: document.documentElement.clientWidth,
        html: document.documentElement.scrollWidth,
        body: document.body.scrollWidth,
        main: Math.round(document.querySelector('.investorMainV2')?.getBoundingClientRect().width ?? 0)
      }))()`);
      if (Math.abs(dimensions.viewport - width) > 2 || dimensions.main <= 0 || dimensions.html > width + 2 || dimensions.body > width + 2 || dimensions.main > width + 2) {
        const overflowCandidates = await session.evaluate(`(() => {
          const viewport = document.documentElement.clientWidth;
          return [...document.querySelectorAll('#main-content *')]
            .map(el => ({tag: el.tagName, classes: el.getAttribute('class') ?? '',
              right: Math.round(el.getBoundingClientRect().right),
              width: Math.round(el.getBoundingClientRect().width)}))
            .filter(el => el.right > viewport + 2)
            .sort((a, b) => b.right - a.right)
            .slice(0, 10);
        })()`);
        const message = `Horisontal mobil-overflyt på ${heading} ved ${width}px: ${JSON.stringify(dimensions)}; kandidater: ${JSON.stringify(overflowCandidates)}`;
        mobileLayoutFailures.push(message);
        console.error(message);
      } else {
        console.log(`Mobil OK: ${slug} ${width}px ${JSON.stringify(dimensions)}`);
      }
    }
  }
  await session.send("Emulation.clearDeviceMetricsOverride");

  if (mobileLayoutFailures.length) {
    throw new Error(`Mobilkontroll feilet i ${mobileLayoutFailures.length} kombinasjoner:\n${mobileLayoutFailures.join("\n")}`);
  }
  console.log("Mobilvisning kontrollert for alle 12 sider ved 320, 390 og 768 px.");
  console.log("Browser-smoke bestått for Oversikt, NAV, Historikk, Tilbakekjøpsprogram, Bemobi, Konsensus, Nyheter og Datakvalitet.");
  await checkRichMobileViews(session);
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

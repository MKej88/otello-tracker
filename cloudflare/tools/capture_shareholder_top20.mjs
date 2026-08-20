import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { chromium } from "playwright-core";

const TARGET_URL = "https://ir.oms.no/component/shareholders?lang=en&token=opera";
const LEGACY_URLS = [
  "https://ir.asp.manamind.com/products/html/shareholders.do?key=opera&lang=en",
  "https://ir.asp.manamind.com/products/html/shareholders.do?key=otello&lang=en",
  "https://ir.asp.manamind.com/products/html/shareholders.do?key=opera_irn&lang=en",
  "https://ir.asp.manamind.com/products/html/shareholders.do?key=otello_irn&lang=en",
];
const EXPECTED_ROWS = 20;
const OUTPUT_PATH = process.env.TOP20_OUTPUT || "/tmp/otec-top20.json";
const DEBUG_DIR = process.env.TOP20_DEBUG_DIR || "/tmp/otec-top20-debug";
const USER_AGENT =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
  "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36";

function clean(value) {
  return String(value ?? "")
    .replace(/\u00a0/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function decodeEntities(value) {
  return clean(
    String(value ?? "")
      .replace(/&nbsp;/gi, " ")
      .replace(/&amp;/gi, "&")
      .replace(/&quot;/gi, '"')
      .replace(/&#39;|&apos;/gi, "'")
      .replace(/&lt;/gi, "<")
      .replace(/&gt;/gi, ">")
  );
}

function stripTags(value) {
  return decodeEntities(String(value ?? "").replace(/<[^>]+>/g, " "));
}

function parseShares(value) {
  const text = clean(value);
  if (!/^(?:\d{4,}|\d{1,3}(?:[ .,'’]\d{3})+)(?:\.00)?$/.test(text)) return null;
  const integerPart = text.endsWith(".00") ? text.slice(0, -3) : text;
  const digits = integerPart.replace(/[^0-9]/g, "");
  if (!digits) return null;
  const parsed = Number.parseInt(digits, 10);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null;
}

function parsePct(value) {
  const text = clean(value).replace(/\s/g, "");
  const match = text.match(/^(\d{1,3}(?:[.,]\d+)?)%?$/);
  if (!match) return null;
  if (!text.includes("%") && !text.includes(",") && !text.includes(".")) return null;
  const parsed = Number.parseFloat(match[1].replace(",", "."));
  return Number.isFinite(parsed) && parsed >= 0 && parsed <= 100 ? parsed : null;
}

function parseRank(value) {
  const match = clean(value).match(/^(\d{1,2})[.)]?$/);
  if (!match) return null;
  const parsed = Number.parseInt(match[1], 10);
  return parsed >= 1 && parsed <= EXPECTED_ROWS ? parsed : null;
}

function pctText(value) {
  if (value == null) return null;
  return Number(value.toFixed(6)).toString();
}

function rowFromCells(rawCells, fallbackRank) {
  const values = rawCells.map(clean).filter(Boolean);
  if (!values.length) return null;

  const explicitRank = parseRank(values[0]);
  const start = explicitRank == null ? 0 : 1;
  let shareIndex = -1;
  for (let index = start; index < values.length; index += 1) {
    if (parseShares(values[index]) != null) {
      shareIndex = index;
      break;
    }
  }
  if (shareIndex < 0) return null;

  const shares = parseShares(values[shareIndex]);
  const beforeShares = values.slice(start, shareIndex);
  if (!beforeShares.length || shares == null) return null;

  const name = clean(beforeShares.join(" "));
  if (!name || /^total\b/i.test(name) || /shareholder|number of shares/i.test(name)) return null;

  const pctIndexes = [];
  for (let index = shareIndex + 1; index < values.length; index += 1) {
    if (parsePct(values[index]) != null) pctIndexes.push(index);
  }
  const ownershipPct = pctIndexes.length ? parsePct(values[pctIndexes.at(-1)]) : null;
  const afterPct = pctIndexes.length ? pctIndexes.at(-1) : shareIndex;
  const trailing = values.filter((value, index) => {
    return index > afterPct && parseShares(value) == null && parsePct(value) == null;
  });

  let country = null;
  let accountType = null;
  if (trailing.length >= 2) {
    accountType = trailing[0];
    country = trailing.at(-1);
  } else if (trailing.length === 1) {
    if (/^[A-Z]{2,3}$/.test(trailing[0])) country = trailing[0];
    else accountType = trailing[0];
  }

  return {
    rank: explicitRank ?? fallbackRank,
    shareholder_name: name,
    country,
    shares,
    ownership_pct: pctText(ownershipPct),
    account_type: accountType,
  };
}

function normalizeRows(candidateRows) {
  const rows = [];
  const seen = new Set();
  for (const candidate of candidateRows) {
    if (!candidate || !candidate.shareholder_name || !candidate.shares) continue;
    const key = clean(candidate.shareholder_name).toLocaleLowerCase("en");
    if (seen.has(key)) continue;
    seen.add(key);
    rows.push({
      rank: rows.length + 1,
      shareholder_name: clean(candidate.shareholder_name),
      country: clean(candidate.country) || null,
      shares: Number(candidate.shares),
      ownership_pct:
        candidate.ownership_pct == null || candidate.ownership_pct === ""
          ? null
          : pctText(Number(candidate.ownership_pct)),
      account_type: clean(candidate.account_type) || null,
    });
    if (rows.length === EXPECTED_ROWS) break;
  }
  return rows;
}

function validateRows(rows) {
  if (rows.length !== EXPECTED_ROWS) {
    throw new Error(`Forventet ${EXPECTED_ROWS} Top 20-rader, fant ${rows.length}`);
  }
  const names = rows.map((row) => clean(row.shareholder_name).toLocaleLowerCase("en"));
  if (new Set(names).size !== EXPECTED_ROWS) throw new Error("Dupliserte aksjonærnavn");
  if (rows.some((row, index) => row.rank !== index + 1 || !Number.isInteger(row.shares) || row.shares <= 0)) {
    throw new Error("Ugyldig rangering eller aksjetall");
  }
  const pctSum = rows.reduce((sum, row) => sum + (row.ownership_pct == null ? 0 : Number(row.ownership_pct)), 0);
  if (pctSum > 100.5) throw new Error(`Ugyldig sum eierandeler: ${pctSum}`);
}

function rowsFromHtml(html) {
  const candidates = [];
  const rowMatches = String(html ?? "").match(/<tr\b[^>]*>[\s\S]*?<\/tr>/gi) || [];
  for (const rowHtml of rowMatches) {
    const cells = [];
    const cellRegex = /<t[dh]\b[^>]*>([\s\S]*?)<\/t[dh]>/gi;
    for (let match = cellRegex.exec(rowHtml); match; match = cellRegex.exec(rowHtml)) {
      cells.push(stripTags(match[1]));
    }
    const row = rowFromCells(cells, candidates.length + 1);
    if (row) candidates.push(row);
  }
  return normalizeRows(candidates);
}

function objectValueByKeys(obj, patterns) {
  for (const [key, value] of Object.entries(obj || {})) {
    const normalized = key.toLowerCase().replace(/[^a-z0-9]/g, "");
    if (patterns.some((pattern) => pattern.test(normalized))) return value;
  }
  return null;
}

function rowFromObject(obj, fallbackRank) {
  if (!obj || Array.isArray(obj) || typeof obj !== "object") return null;
  const name = objectValueByKeys(obj, [/shareholder/, /holdername/, /^owner/, /^name$/, /investor/]);
  const sharesRaw = objectValueByKeys(obj, [/numberofshares/, /^shares$/, /sharecount/, /holding/, /quantity/]);
  const shares = parseShares(String(sharesRaw ?? "").replace(/\.0+$/, ""));
  if (!name || shares == null) return null;
  const pctRaw = objectValueByKeys(obj, [/ownership/, /percentage/, /percent/, /pct/]);
  const country = objectValueByKeys(obj, [/country/, /nation/]);
  const account = objectValueByKeys(obj, [/accounttype/, /account/, /type/]);
  const rankRaw = objectValueByKeys(obj, [/^rank$/, /position/]);
  return {
    rank: parseRank(String(rankRaw ?? "")) ?? fallbackRank,
    shareholder_name: clean(name),
    country: clean(country) || null,
    shares,
    ownership_pct: pctText(parsePct(String(pctRaw ?? ""))),
    account_type: clean(account) || null,
  };
}

function candidateRowsFromJson(value) {
  let best = [];
  const visit = (node) => {
    if (best.length === EXPECTED_ROWS) return;
    if (Array.isArray(node)) {
      const direct = normalizeRows(node.map((item, index) => rowFromObject(item, index + 1)));
      if (direct.length > best.length) best = direct;
      if (node.every((item) => Array.isArray(item))) {
        const matrix = normalizeRows(node.map((cells, index) => rowFromCells(cells, index + 1)));
        if (matrix.length > best.length) best = matrix;
      }
      for (const item of node) visit(item);
    } else if (node && typeof node === "object") {
      for (const child of Object.values(node)) visit(child);
    }
  };
  visit(value);
  return best;
}

async function legacyAttempt() {
  const diagnostics = [];
  for (const url of LEGACY_URLS) {
    try {
      const response = await fetch(url, {
        redirect: "follow",
        headers: { "User-Agent": USER_AGENT, Accept: "text/html,application/xhtml+xml" },
      });
      const html = await response.text();
      const rows = response.ok ? rowsFromHtml(html) : [];
      diagnostics.push({ url, status: response.status, rows: rows.length, hint: clean(stripTags(html)).slice(0, 180) });
      if (rows.length === EXPECTED_ROWS) {
        return { rows, method: "GITHUB_HTTP_LEGACY", source_url: url, diagnostics };
      }
    } catch (error) {
      diagnostics.push({ url, error: String(error), rows: 0 });
    }
  }
  return { rows: [], diagnostics };
}

function findChrome() {
  const candidates = [
    process.env.CHROME_PATH,
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
  ].filter(Boolean);
  return candidates[0];
}

async function browserAttempt() {
  const browser = await chromium.launch({
    executablePath: findChrome(),
    headless: true,
    args: ["--no-sandbox", "--disable-dev-shm-usage"],
  });
  const context = await browser.newContext({ userAgent: USER_AGENT, viewport: { width: 1440, height: 1100 } });
  const page = await context.newPage();
  const network = [];
  const jsonCandidates = [];
  const pendingBodies = [];

  page.on("response", (response) => {
    const task = (async () => {
      const request = response.request();
      const resourceType = request.resourceType();
      const headers = response.headers();
      const contentType = headers["content-type"] || "";
      const item = {
        url: response.url(),
        status: response.status(),
        resource_type: resourceType,
        content_type: contentType,
      };
      if (["xhr", "fetch"].includes(resourceType) || /json|javascript|text\//i.test(contentType)) {
        try {
          const body = await response.text();
          item.body_hint = clean(body).slice(0, 400);
          if (/json/i.test(contentType) || /^[\[{]/.test(body.trim())) {
            try {
              const parsed = JSON.parse(body);
              jsonCandidates.push({ url: response.url(), value: parsed });
            } catch {
              // Not valid JSON; keep only the diagnostic hint.
            }
          }
        } catch (error) {
          item.body_error = String(error);
        }
      }
      network.push(item);
    })();
    pendingBodies.push(task);
  });

  let navigationError = null;
  try {
    await page.goto(TARGET_URL, { waitUntil: "domcontentloaded", timeout: 45_000 });
    await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {});
    await page.waitForTimeout(5_000);
  } catch (error) {
    navigationError = String(error);
  }

  await Promise.allSettled(pendingBodies);

  let bestRows = [];
  let bestSource = null;
  for (const candidate of jsonCandidates) {
    const rows = candidateRowsFromJson(candidate.value);
    if (rows.length > bestRows.length) {
      bestRows = rows;
      bestSource = `json:${candidate.url}`;
    }
  }

  const frameDiagnostics = [];
  for (const frame of page.frames()) {
    const selectors = ["table tbody tr", "table tr", "[role='row']"];
    for (const selector of selectors) {
      try {
        const matrices = await frame.locator(selector).evaluateAll((elements) =>
          elements.map((element) => {
            const cells = Array.from(
              element.querySelectorAll("th,td,[role='cell'],[role='gridcell'],[role='rowheader'],[role='columnheader']")
            ).map((cell) => (cell.textContent || "").trim());
            if (cells.length) return cells;
            return (element.textContent || "").split(/\t|\n/).map((part) => part.trim()).filter(Boolean);
          })
        );
        const rows = normalizeRows(matrices.map((cells, index) => rowFromCells(cells, index + 1)));
        frameDiagnostics.push({ url: frame.url(), selector, elements: matrices.length, parsed_rows: rows.length });
        if (rows.length > bestRows.length) {
          bestRows = rows;
          bestSource = `dom:${frame.url()}:${selector}`;
        }
      } catch (error) {
        frameDiagnostics.push({ url: frame.url(), selector, error: String(error), parsed_rows: 0 });
      }
    }
  }

  const title = await page.title().catch(() => "");
  const bodyText = await page.locator("body").innerText().catch(() => "");
  const html = await page.content().catch(() => "");
  await fs.mkdir(DEBUG_DIR, { recursive: true });
  await fs.writeFile(path.join(DEBUG_DIR, "page.html"), html, "utf8");
  await fs.writeFile(path.join(DEBUG_DIR, "network.json"), JSON.stringify(network, null, 2), "utf8");
  await fs.writeFile(
    path.join(DEBUG_DIR, "browser.json"),
    JSON.stringify({ title, navigationError, frameDiagnostics, body_hint: clean(bodyText).slice(0, 1200) }, null, 2),
    "utf8"
  );
  await page.screenshot({ path: path.join(DEBUG_DIR, "page.png"), fullPage: true }).catch(() => {});
  await browser.close();

  return {
    rows: bestRows,
    method: bestRows.length === EXPECTED_ROWS ? "GITHUB_PLAYWRIGHT" : null,
    source_url: TARGET_URL,
    diagnostics: {
      title,
      navigationError,
      bestSource,
      bestRows: bestRows.length,
      frameDiagnostics,
      networkRequests: network.length,
      networkHints: network.filter((item) => ["xhr", "fetch"].includes(item.resource_type)).slice(0, 30),
    },
  };
}

async function main() {
  await fs.mkdir(DEBUG_DIR, { recursive: true });
  const legacy = await legacyAttempt();
  if (legacy.rows.length === EXPECTED_ROWS) {
    validateRows(legacy.rows);
    const payload = {
      rows: legacy.rows,
      source_url: legacy.source_url,
      method: legacy.method,
      captured_at: new Date().toISOString(),
      diagnostics: { legacy: legacy.diagnostics },
    };
    await fs.writeFile(OUTPUT_PATH, JSON.stringify(payload, null, 2), "utf8");
    console.log(`Captured ${EXPECTED_ROWS} shareholders via ${legacy.method}.`);
    return;
  }

  const browser = await browserAttempt();
  const rows = normalizeRows(browser.rows);
  try {
    validateRows(rows);
  } catch (error) {
    const diagnostics = { legacy: legacy.diagnostics, browser: browser.diagnostics };
    await fs.writeFile(path.join(DEBUG_DIR, "failure.json"), JSON.stringify(diagnostics, null, 2), "utf8");
    throw new Error(
      `Top 20 kunne ikke leses fra GitHub-runner. legacy=${JSON.stringify(legacy.diagnostics)}; ` +
        `browser=${JSON.stringify(browser.diagnostics)}`,
      { cause: error }
    );
  }

  const payload = {
    rows,
    source_url: browser.source_url,
    method: browser.method,
    captured_at: new Date().toISOString(),
    diagnostics: { legacy: legacy.diagnostics, browser: browser.diagnostics },
  };
  await fs.writeFile(OUTPUT_PATH, JSON.stringify(payload, null, 2), "utf8");
  console.log(`Captured ${EXPECTED_ROWS} shareholders via ${browser.method}.`);
}

await main();

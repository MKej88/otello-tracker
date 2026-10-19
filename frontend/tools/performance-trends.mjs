/**
 * Read historical production-performance workflow artifacts and append a
 * seven-day trend table to Job Summary + current JSON artifact.
 * Only production-main history counts; no browser-side collection.
 */
import { execFileSync } from "node:child_process";
import { appendFileSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { buildTrends } from "./performance-trend-core.mjs";

const FILE_NAME = process.env.PERF_REPORT_PATH || "performance-report.json";
const REPOSITORY = process.env.GITHUB_REPOSITORY || "";
const TOKEN = process.env.GITHUB_TOKEN || "";
const RUN_ID = Number(process.env.GITHUB_RUN_ID || 0);
const API = "https://api.github.com";
const ARTIFACT = "otello-production-performance";
const TIMEOUT_MS = 12000;
const MAX_HISTORY = 42;
const WINDOW_DAYS = 14;

const ROUTES = [
  { label: "Oversikt", hash: "#oversikt" },
  { label: "NAV", hash: "#nav" },
  { label: "NAV-sensitivitet", hash: "#nav-sensitivitet" },
  { label: "Historikk", hash: "#historikk" },
  { label: "Tilbakekjøpsprogram", hash: "#tilbakekjop" },
  { label: "Cash", hash: "#cash" },
  { label: "Bemobi", hash: "#bemobi" },
  { label: "BRL/NOK", hash: "#brl-nok" },
  { label: "Brasil", hash: "#brasil" },
  { label: "Konsensus", hash: "#konsensus" },
  { label: "Nyheter", hash: "#nyheter" },
  { label: "Datakvalitet", hash: "#datakvalitet" },
];

function formatMs(value) {
  return value == null ? "–" : value + " ms";
}
function formatChange(trend) {
  if (!trend.comparable) return "–";
  const value = trend.changePct;
  return (value > 0 ? "+" : "") + String(value) + " %";
}
function sampleCount(trend) {
  return trend.currentSamples + "/" + trend.priorSamples;
}
function warn(message) {
  // GitHub Actions annotations – technical warning, not an external alert.
  console.log("::warning::" + message.replace(/\r?\n/g, " "));
}

async function githubRequest(url, binary = false) {
  const response = await fetch(url, {
    headers: {
      authorization: "Bearer " + TOKEN,
      accept: "application/vnd.github+json",
      "x-github-api-version": "2022-11-28",
    },
    signal: AbortSignal.timeout(TIMEOUT_MS),
  });
  if (!response.ok) throw new Error("GitHub artifact API: HTTP " + response.status);
  return binary ? Buffer.from(await response.arrayBuffer()) : response.json();
}

function extractArtifact(bytes) {
  // unzip is preinstalled on ubuntu-latest, so no package/dependency needed.
  const dir = mkdtempSync(join(tmpdir(), "otello-trend-"));
  const zipPath = join(dir, "artifact.zip");
  try {
    writeFileSync(zipPath, bytes);
    const text = execFileSync("unzip", ["-p", zipPath, "performance-report.json"], {
      encoding: "utf8", maxBuffer: 2 * 1024 * 1024, timeout: 6000, stdio: ["ignore", "pipe", "ignore"],
    });
    return JSON.parse(text);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

async function getHistoricalReports(asOf) {
  const result = { reports: [], warnings: [], discovered: 0 };
  if (!TOKEN || !/^[a-zA-Z0-9_.-]+\/[a-zA-Z0-9_.-]+$/.test(REPOSITORY)) {
    result.warnings.push("Mangler GitHub-token eller repo-identifikator; trendhistorikk kunne ikke hentes.");
    return result;
  }
  const cutoff = Date.parse(asOf) - WINDOW_DAYS * 86400000;
  try {
    const url = API + "/repos/" + REPOSITORY + "/actions/artifacts" +
      "?name=" + encodeURIComponent(ARTIFACT) + "&per_page=100";
    const payload = await githubRequest(url);
    const eligible = (payload.artifacts || [])
      .filter((a) =>
        !a.expired && Date.parse(a.created_at) >= cutoff &&
        a.workflow_run?.head_branch === "main" &&
        a.workflow_run?.id !== RUN_ID &&
        a.size_in_bytes > 0 && a.size_in_bytes < 2 * 1024 * 1024
      )
      .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at));
    // Re-runs can have more than one artifact for the same workflow run.
    const seenRuns = new Set();
    const artifacts = eligible.filter((a) => {
      if (seenRuns.has(a.workflow_run.id)) return false;
      seenRuns.add(a.workflow_run.id);
      return true;
    }).slice(0, MAX_HISTORY);
    result.discovered = artifacts.length;

    for (const artifact of artifacts) {
      try {
        const zipped = await githubRequest(artifact.archive_download_url, true);
        const report = extractArtifact(zipped);
        // Incomplete or failed monitor runs must not influence the baseline.
        if (Array.isArray(report?.browser) && report.browser.length === ROUTES.length &&
          Array.isArray(report?.navigation) && report.navigation.length === ROUTES.length &&
          Array.isArray(report?.errors) && report.errors.length === 0 &&
          typeof report?.checkedAt === "string") {
          result.reports.push(report);
        }
      } catch (error) {
        result.warnings.push("Kunne ikke lese en historisk måling (artifact " +
          artifact.id + "): " + String(error));
      }
    }
    // Fail open for missing history: new installations need two weeks of data.
    if (payload.total_count > 100 && eligible.length === 100) {
      result.warnings.push("Over 100 rapporter funnet; kun første side ble kontrollert.");
    }
  } catch (error) {
    result.warnings.push("GitHub-historikk kunne ikke hentes: " + String(error));
  }
  return result;
}

function markdown(trend, history) {
  const rows = trend.routes.map((row) => [
    row.label,
    formatMs(row.cold.currentMedianMs),
    formatMs(row.cold.priorMedianMs),
    formatChange(row.cold),
    formatMs(row.navigation.currentMedianMs),
    formatMs(row.navigation.priorMedianMs),
    formatChange(row.navigation),
    row.cold.regression || row.navigation.regression ? "**FORVERRET**" : "–",
  ].join(" | "));
  const apiRows = trend.apis.map((a) => [
    "\`" + a.endpoint.replace(/\|/g, "") + "\`",
    formatMs(a.timing.currentMedianMs),
    formatMs(a.timing.priorMedianMs),
    formatChange(a.timing),
    a.timing.regression ? "**FORVERRET**" : "–",
  ].join(" | "));

  return [
    "## Ytelsestrend – 7 dager mot foregående 7 dager",
    "",
    "Kilde: syntetiske produksjonsmålinger fra \`main\`. Hver måling utføres av",
    "GitHub-hostet Chrome og representerer ikke reelle brukere.",
    "",
    "| Side | Direkte: 7d | Før: 7d | Endring | Sideskift: 7d | Før: 7d | Endring | Status |",
    "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ...rows.map((row) => "| " + row + " |"),
    "",
    "### API-trend",
    "",
    "| Endepunkt | 7d median | Forrige 7d | Endring | Status |",
    "| --- | ---: | ---: | ---: | --- |",
    ...apiRows.map((row) => "| " + row + " |"),
    "",
    "### Tolkning og varsler",
    "",
    ...trend.regressions.map((r) =>
      "- **FORVERRET " + r.scope + ": " + r.key + "**: " +
      formatMs(r.priorMedianMs) + " → " + formatMs(r.currentMedianMs) +
      " (" + formatChange(r) + "); " + sampleCount(r) + " målinger (7d / før)."),
    ...(trend.regressions.length ? [] : ["Ingen bekreftede vesentlige ytelsesforverringer."]),
    "",
    "Sammenligning vises først med minst 6 målinger på minst 3 forskjellige dager " +
    "**i hver** 7-dagersperiode. De to siste målingene må dessuten vise vedvarende treghet.",
    "Varslingsgrenser: direktelasting +35 % og +500 ms (minst 1 s); " +
    "sideskifte +35 % og +300 ms (minst 600 ms); API +45 % og +150 ms (minst 250 ms).",
    "",
    "Antall historiske målinger: " + history.reports.length +
    " lest fra " + history.discovered + " GitHub-artifacts; med dagens kjøring " +
    trend.reportCount + " innenfor siste 14 dager.",
    ...(history.warnings.length
      ? ["", "**Begrenset historikk:**", ...history.warnings.map((w) => "- " + w)]
      : []),
    "",
  ].join("\n") + "\n";
}

async function main() {
  const current = JSON.parse(readFileSync(FILE_NAME, "utf8"));
  const asOf = current.checkedAt;
  if (typeof asOf !== "string" || !Array.isArray(current.browser)) {
    throw new Error("Current production report is incomplete");
  }
  const history = await getHistoricalReports(asOf);
  const trend = buildTrends([...history.reports, current], asOf, ROUTES);
  current.trend = {
    ...trend,
    historyArtifacts: history.discovered,
    historyRead: history.reports.length,
    historyWarnings: history.warnings,
  };
  writeFileSync(FILE_NAME, JSON.stringify(current, null, 2) + "\n");
  const summary = markdown(trend, history);
  console.log(summary);
  if (process.env.GITHUB_STEP_SUMMARY) appendFileSync(process.env.GITHUB_STEP_SUMMARY, summary);
  for (const warning of history.warnings) warn("Ytelsestrend: " + warning);
  for (const regression of trend.regressions) {
    warn("BEKREFTET YTELSESFORVERRING " + regression.scope + " " +
      regression.key + ": " + regression.priorMedianMs + " -> " +
      regression.currentMedianMs + " ms (" + regression.changePct + "%)");
  }
  // Failure sends an Actions failure signal (subject to GitHub notification
  // settings). Avoid blocking PRs for production regressions unrelated to PR.
  if (trend.regressions.length && process.env.GITHUB_EVENT_NAME === "schedule" &&
      process.env.GITHUB_REF === "refs/heads/main") {
    process.stderr.write("Significant persistent production performance regression detected.\n");
    process.exitCode = 1;
  }
}
await main();

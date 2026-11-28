import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (name: string) => readFileSync(new URL(`../src/${name}`, import.meta.url), "utf8");
const views = read("investorViews.ts");
const shell = read("styles.css");
const shared = read("investor-v2.css");
const navigation = read("navigation-groups.css");
const sensitivity = read("nav-sensitivity.css");
const sensitivityPage = read("NavSensitivityPage.tsx");
const historyPage = read("EstimatedHistoryPage.tsx");
const cash = read("cash-page.css");
const buyback = read("buyback-page.css");
const buybackPage = read("BuybackPage.tsx");

test("all twelve investor routes are represented in the mobile navigation and browser audit", () => {
  const smoke = readFileSync(new URL("./browser-smoke.mjs", import.meta.url), "utf8");
  for (const slug of ["oversikt", "nav", "nav-sensitivitet", "historikk", "tilbakekjop", "cash",
    "bemobi", "brl-nok", "brasil", "konsensus", "nyheter", "datakvalitet"]) {
    assert.ok(views.includes(`"${slug}"`), `Route missing: ${slug}`);
    assert.ok(smoke.includes(`"${slug}"`), `Mobile audit missing: ${slug}`);
  }
  for (const width of [320, 390, 768]) {
    assert.ok(smoke.includes(`[390, 320, 768]`), `No viewport audit for ${width}px`);
  }
});

test("phone shell and navigation retain usable width and accessible tap targets", () => {
  assert.match(shell, /@media \(max-width: 480px\)/);
  assert.match(shell, /\.main\.investorMainV2\s*\{[^}]*padding: 16px 12px 28px;/s);
  assert.match(shared, /Shared responsive content sizing/);
  assert.match(navigation, /\.mobileInvestorNav \.navItem\s*\{\s*min-height: 44px;/s);
});

test("sensitivity and buyback wide financial tables explicitly preserve horizontal scrolling", () => {
  assert.match(sensitivityPage, /className="sensitivityScrollHint"/);
  assert.match(sensitivity, /\.sensitivityTableWrap\s*\{[^}]*max-width: 100%;[^}]*overscroll-behavior-x: contain;/s);
  assert.match(buybackPage, /className="buybackTableHint"/);
  assert.match(buyback, /\.buybackTableWrap\s*\{[^}]*max-width: 100%;[^}]*overscroll-behavior-x: contain;/s);
});

test("history and cash use two-column mobile KPI layouts instead of full-height lists", () => {
  assert.match(historyPage, /className="historyKpiGrid"/);
  assert.match(shared, /@media\s*\(max-width:\s*1100px\)\s*\{[\s\S]*?\.historyKpiGrid\s*\{\s*grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\);/);
  assert.match(shared, /@media\s*\(max-width:\s*760px\)\s*\{[\s\S]*?\.historyKpiGrid\s*\{\s*grid-template-columns:\s*1fr\s+1fr;/);
  assert.match(cash, /@media \(min-width: 380px\) and \(max-width: 760px\)/);
  assert.match(cash, /\.cashKpiGrid,\s*\.cashBuybackResultsPrimary\s*\{\s*grid-template-columns: repeat\(2, minmax\(0, 1fr\)\);/);
});


test("browser smoke verifies current overview markup and actual mobile route content", () => {
  const smoke = readFileSync(new URL("./browser-smoke.mjs", import.meta.url), "utf8");
  const overview = read("OverviewPage.tsx");
  assert.ok(overview.includes("overviewNavCardV3"));
  assert.ok(overview.includes("overviewDriverGrid"));
  assert.ok(smoke.includes(".overviewV3 .overviewNavCardV3 h2"));
  assert.ok(smoke.includes(".overviewDriverGrid .overviewDriverCard .label"));
  assert.ok(!smoke.includes(".overviewV2 .estimatedHero h2"));
  assert.ok(smoke.includes("for (const [slug, heading, readySelector] of mobileViews)"));
  assert.ok(smoke.includes('Boolean(document.querySelector(${JSON.stringify(readySelector)}))'));
  assert.ok(smoke.includes("Math.abs(dimensions.viewport - width) > 2"));
  assert.ok(smoke.includes("Mobil OK:"));
});

test("CI propagates browser smoke failures instead of tee success", () => {
  const ci = readFileSync(new URL("../../.github/workflows/ci.yml", import.meta.url), "utf8");
  const smokeStep = ci.split("End-to-end Worker/reference parity and real browser smoke", 2)[1];
  assert.ok(smokeStep);
  const pipefail = smokeStep.indexOf("set -o pipefail");
  const pipeline = smokeStep.indexOf('2>&1 | tee "$browser_log"');
  assert.ok(pipefail >= 0 && pipeline > pipefail);
});


test("history smoke accepts the empty state only when the exact API request confirms it", () => {
  const smoke = readFileSync(new URL("./browser-smoke.mjs", import.meta.url), "utf8");
  const history = read("EstimatedHistoryPage.tsx");
  assert.ok(smoke.includes("/api/dashboard/discount-history?days=365&max_points=72"));
  assert.ok(smoke.includes('typeof history?.ready !== "boolean"'));
  assert.ok(smoke.includes("history.ready && !history.statistics"));
  assert.ok(smoke.includes('const historyReadySelector = history.ready'));
  assert.ok(smoke.includes(".historyV2 .historyAxisCard"));
  assert.ok(smoke.includes(".historyV2 .resourceNotice.empty"));
  assert.ok(smoke.includes(".historyV2 .resourceNotice.error"));
  assert.ok(smoke.includes('["historikk","Historisk NAV-rabatt",historyReadySelector]'));
  assert.ok(history.includes('data && !data.ready'));
  assert.ok(history.includes('data?.ready && stats'));
});

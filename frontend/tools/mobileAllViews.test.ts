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
const history = read("history-page.css");
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
  assert.match(history, /\.historyKpiGrid\s*\{\s*grid-template-columns: repeat\(2, minmax\(0, 1fr\)\);/);
  assert.match(cash, /@media \(min-width: 380px\) and \(max-width: 760px\)/);
  assert.match(cash, /\.cashKpiGrid,\s*\.cashBuybackResultsPrimary\s*\{\s*grid-template-columns: repeat\(2, minmax\(0, 1fr\)\);/);
});

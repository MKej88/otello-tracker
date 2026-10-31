import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const page = readFileSync(new URL("../src/FxPage.tsx", import.meta.url), "utf8");
const css = readFileSync(new URL("../src/fx-page.css", import.meta.url), "utf8");

test("BRL/NOK chart sizes its viewBox to the available width", () => {
  assert.match(page, /useLayoutEffect\(/);
  assert.match(page, /ResizeObserver\(measure\)/);
  assert.match(page, /const width = chartWidth;/);
  assert.match(page, /const height = width < 620 \? 270 : 330;/);
  assert.match(page, /viewBox={`0 0 \$\{width\} \$\{height\}`}/);
  assert.match(css, /\.fxChart\s*\{\s*height: auto;\s*min-height: 0;/);
});

test("sensitivity cells keep the five original financial columns as mobile labels", () => {
  for (const label of ["BRL-bevegelse", "BRL/NOK", "Bemobi-post", "Endring", "Direkte / OTEC"]) {
    assert.ok(page.includes(`data-label="${label}"`), `Missing mobile label: ${label}`);
  }
  assert.match(css, /\.fxTable tbody td::before\s*\{\s*content: attr\(data-label\);/);
  assert.match(css, /\.fxTable tbody tr\.current\s*\{/);
});

test("mobile FX layout keeps filters, KPIs, history, and scenarios readable", () => {
  assert.match(css, /@media \(max-width: 680px\)/);
  assert.match(css, /\.fxRangeButtons\s*\{\s*display: grid;/);
  assert.match(css, /\.fxKpi:first-child,\s*\.fxKpi:last-child\s*\{\s*grid-column: 1 \/ -1;/);
  assert.match(css, /\.fxHistorySummary > div:last-child\s*\{\s*grid-column: 1 \/ -1;/);
  assert.match(css, /\.fxTableWrap\s*\{\s*min-width: 0;\s*overflow: visible;/);
});

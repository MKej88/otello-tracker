import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const consensus = readFileSync(new URL("../src/ConsensusPage.tsx", import.meta.url), "utf8");
const consensusCss = readFileSync(new URL("../src/consensus-page.css", import.meta.url), "utf8");
const bemobi = readFileSync(new URL("../src/BemobiPageBase.tsx", import.meta.url), "utf8");
const bemobiCss = readFileSync(new URL("../src/bemobi-page.css", import.meta.url), "utf8");
const valuationCss = readFileSync(new URL("../src/bemobi-valuation.css", import.meta.url), "utf8");

test("consensus retains source links and exposes each broker on mobile", () => {
  assert.match(consensus, /className="consensusMobileBrokerLabel"/);
  assert.match(consensus, /<SourceLink url={broker\.sourceUrls\[0\]}>{broker\.broker}<\/SourceLink>/);
  assert.match(consensusCss, /@media \(max-width: 640px\)/);
  assert.match(consensusCss, /\.consensusBrokerTable tbody tr\s*,[\s\S]*?\.consensusComparisonTable tbody tr\s*\{\s*display: grid;/);
});

test("comparison values have their original quarter labels in mobile cards", () => {
  assert.match(consensus, /data-label={`\$\{nextQuarter\?\.period/);
  assert.match(consensus, /data-label={report\?\.period/);
  assert.match(consensus, /data-label="Beat-grense"/);
  assert.match(consensusCss, /content: attr\(data-label\)/);
});

test("Bemobi exposes mobile labels for all four quarterly measures", () => {
  for (const label of ["Omsetning", "Justert EBITDA", "Margin", "Justert resultat"]) {
    assert.ok(bemobi.includes(`data-label="${label}"`), `Mangler: ${label}`);
  }
  assert.match(bemobiCss, /\.bemobiQuarterTable tbody tr\s*\{\s*display: grid;/);
  assert.match(valuationCss, /@media \(min-width: 361px\) and \(max-width: 600px\)/);
});

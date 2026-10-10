import assert from "node:assert/strict";
import test from "node:test";
import { buildNextQuarterConsensus, type NextQuarterEstimate } from "../src/nextQuarterConsensus.ts";

const amount = (broker: string, metric: string, value: number, date = "2026-10-08"): NextQuarterEstimate => ({
  broker, metric, label: metric, value_mbrl: value, published_date: date,
  source_url: `https://example.test/${broker}/preview`,
});
const btg: NextQuarterEstimate[] = [
  amount("BTG Pactual", "revenue_mbrl", 239.8), amount("BTG Pactual", "adjusted_ebitda_mbrl", 85.5),
  amount("BTG Pactual", "adjusted_net_income_mbrl", 48), amount("BTG Pactual", "operating_free_cash_flow_mbrl", 69.9),
  { broker: "BTG Pactual", metric: "ebitda_margin_pct", label: "Justert EBITDA-margin", value_pct: 35.7, published_date: "2026-10-08" },
];
// XP values here are hypothetical test inputs, not published estimates.
const xp = [
  amount("XP", "revenue_mbrl", 250, "2026-10-09"), amount("XP", "adjusted_ebitda_mbrl", 86, "2026-10-09"),
  amount("XP", "adjusted_net_income_mbrl", 49, "2026-10-09"),
];

test("XP får egen rad og lik vekt med BTG i snittet", () => {
  const result = buildNextQuarterConsensus([...btg, ...xp]);
  assert.deepEqual(result.brokers.map((row) => row.broker), ["BTG Pactual", "XP"]);
  assert.deepEqual(result.averages["revenue_mbrl:mbrl"], { value: 244.9, count: 2 });
  assert.equal(result.averages["adjusted_ebitda_mbrl:mbrl"].value, 85.75);
  assert.equal(result.averages["adjusted_net_income_mbrl:mbrl"].value, 48.5);
  assert.equal(result.brokers[1].publishedDate, "2026-10-09");
  assert.deepEqual(result.brokers[1].sourceUrls, ["https://example.test/XP/preview"]);
});

test("manglende tall regnes ikke som null og n varierer mellom kolonner", () => {
  const result = buildNextQuarterConsensus([...btg, ...xp]);
  assert.deepEqual(result.averages["operating_free_cash_flow_mbrl:mbrl"], { value: 69.9, count: 1 });
  assert.equal(result.brokers[1].values["operating_free_cash_flow_mbrl:mbrl"], undefined);
  assert.deepEqual(buildNextQuarterConsensus(btg).averages["revenue_mbrl:mbrl"], { value: 239.8, count: 1 });
});

test("margin kommer fra samme meglerhus og eksplisitt margin foretrekkes", () => {
  const result = buildNextQuarterConsensus([...btg, ...xp]);
  assert.deepEqual(result.brokers[0].values["ebitda_margin_pct:pct"], { value: 35.7, derived: false });
  assert.deepEqual(result.brokers[1].values["ebitda_margin_pct:pct"], { value: 34.4, derived: true });
  assert.ok(Math.abs(result.averages["ebitda_margin_pct:pct"].value! - 35.05) < 1e-10);
  const separate = buildNextQuarterConsensus([amount("BTG", "revenue_mbrl", 240), amount("XP", "adjusted_ebitda_mbrl", 86)]);
  assert.equal(separate.averages["ebitda_margin_pct:pct"], undefined);
  const zero = buildNextQuarterConsensus([amount("XP", "revenue_mbrl", 0, "2026-10-09"), ...xp.slice(1)]);
  assert.equal(zero.averages["ebitda_margin_pct:pct"], undefined);
});

test("nyeste publikasjon erstatter eldre sett og duplikater gir ikke ekstra vekt", () => {
  const result = buildNextQuarterConsensus([
    ...btg, ...xp, amount(" xp ", "revenue_mbrl", 250, "2026-10-09"),
    amount("XP", "revenue_mbrl", 200, "2026-10-07"), amount("XP", "operating_free_cash_flow_mbrl", 60, "2026-10-07"),
  ]);
  assert.equal(result.brokers.length, 2);
  assert.deepEqual(result.averages["revenue_mbrl:mbrl"], { value: 244.9, count: 2 });
  assert.deepEqual(result.averages["operating_free_cash_flow_mbrl:mbrl"], { value: 69.9, count: 1 });
});

test("cash profit og ordinært resultat blandes ikke med justert nettoresultat", () => {
  const result = buildNextQuarterConsensus([...btg, amount("XP", "cash_profit_mbrl", 49), amount("Other", "net_income_mbrl", 42)]);
  assert.deepEqual(result.averages["adjusted_net_income_mbrl:mbrl"], { value: 48, count: 1 });
  assert.deepEqual(result.averages["cash_profit_mbrl:mbrl"], { value: 49, count: 1 });
  assert.deepEqual(result.averages["net_income_mbrl:mbrl"], { value: 42, count: 1 });
});

test("enheter holdes adskilt, null teller, og ugyldige eller tvetydige verdier utelates", () => {
  const result = buildNextQuarterConsensus([
    amount("BTG", "revenue_mbrl", 100), amount("XP", "revenue_mbrl", 0), amount("Invalid", "revenue_mbrl", NaN),
    amount("Infinity", "revenue_mbrl", Infinity),
    { broker: "Ambiguous", metric: "revenue_mbrl", label: "Revenue", value_mbrl: 150, value_pct: 20 },
    { broker: "Percent", metric: "revenue_mbrl", label: "Revenue", value_pct: 30 },
  ]);
  assert.deepEqual(result.averages["revenue_mbrl:mbrl"], { value: 50, count: 2 });
  assert.deepEqual(result.averages["revenue_mbrl:pct"], { value: 30, count: 1 });
  assert.equal(result.brokers.length, 3);
  assert.deepEqual(buildNextQuarterConsensus([]).brokers, []);
});

test("verifisert PDF-verdi beholdes ved duplikat fra samme publikasjon", () => {
  const result = buildNextQuarterConsensus([
    { ...amount("BTG", "revenue_mbrl", 239.8), source_evidence: "PDF_TABLE_VERIFIED" }, amount("BTG", "revenue_mbrl", 240),
  ]);
  assert.deepEqual(result.averages["revenue_mbrl:mbrl"], { value: 239.8, count: 1 });
});

import assert from "node:assert/strict";
import test from "node:test";
import { currentPeriodNetCash, netCashUnavailableReason, reportedQ3Jcp, verifiedReportedCash } from "../src/bemobiCashQuality.ts";

test("3Q26 bad 2025-as-cash is suppressed across derived figures", () => {
  assert.equal(verifiedReportedCash({ period: "3Q26", cash_mbrl: 2025 }), null);
  assert.equal(verifiedReportedCash({ period: "3Q26", cash_mbrl: 319, cash_quality: "REJECTED_IMPLAUSIBLE_CASH" }), null);
  assert.equal(verifiedReportedCash({ period: "3Q26", cash_mbrl: 319, cash_quality: "OFFICIAL_REPORTED" }), 319);
  assert.equal(verifiedReportedCash({ cash_mbrl: NaN }), null);
  assert.equal(verifiedReportedCash({ cash_mbrl: 0 }), null);
});

test("net cash is not relabelled 3Q26 from a 2Q26 EV anchor", () => {
  const report = { period: "3Q26", cash_mbrl: 319 };
  const stale = { net_cash_mbrl: 287.2, ev_anchor_period: "2Q26" };
  assert.deepEqual(currentPeriodNetCash(report, stale), { value: null, basis: "unavailable" });
  assert.deepEqual(currentPeriodNetCash(report, {
    ...stale, ev_anchor_period: "3Q26",
  }), { value: 287.2, basis: "current_anchor" });
});

test("matching 3Q26 CVM net debt takes precedence over older anchor", () => {
  const result = currentPeriodNetCash(
    { period: "3Q26", cash_mbrl: 319 },
    {
      net_cash_mbrl: 287.2, ev_anchor_period: "2Q26",
      source_quarters: [{ period: "2Q26", reported_net_debt_mbrl: -286.8 },
        { period: "3Q26", reported_net_debt_mbrl: -277.8 }],
    },
  );
  assert.deepEqual(result, { value: 277.8, basis: "reported_quarter" });
});

test("net cash cannot exceed actual cash balance", () => {
  assert.deepEqual(currentPeriodNetCash(
    { period: "3Q26", cash_mbrl: 319 },
    { ev_anchor_period: "3Q26", net_cash_mbrl: 500 },
  ), { value: null, basis: "unavailable" });
});

test("3Q26 JCP uses only confirmed company action, never old 16.19 tracker estimate", () => {
  const confirmed = {
    type: "JCP",
    announcement_date: "2026-11-12",
    ex_date: "2026-11-18",
    gross_total_mbrl: 16,
  };
  assert.equal(reportedQ3Jcp(confirmed), 16);
  assert.equal(reportedQ3Jcp({ ...confirmed, type: "DIVIDEND" }), null);
  assert.equal(reportedQ3Jcp({ ...confirmed, ex_date: "2026-08-17" }), null);
  assert.equal(reportedQ3Jcp({ ...confirmed, gross_total_mbrl: null }), null);
  assert.equal(reportedQ3Jcp(undefined), null);
});

test("CVM-only current quarter is used for net cash, without older EV anchor", () => {
  const report = { period: "3Q26", cash_mbrl: 319 };
  const valuation = {
    ev_anchor_period: "2Q26", net_cash_mbrl: 287.2,
    source_quarters: [{ period: "2Q26", reported_net_debt_mbrl: -287.2 }],
    reported_balance_quarters: [
      { period: "2Q26", reported_net_debt_mbrl: -287.2 },
      { period: "3Q26", reported_net_debt_mbrl: -275 },
    ],
  };
  assert.deepEqual(currentPeriodNetCash(report, valuation), {
    value: 275, basis: "reported_quarter",
  });
  assert.equal(netCashUnavailableReason(report, valuation), null);
});

test("unverified current-quarter debt has an explicit period-specific explanation", () => {
  const report = { period: "3Q26", cash_mbrl: 319 };
  const valuation = {
    ev_anchor_period: "2Q26", net_cash_mbrl: 287.2,
    reported_balance_quarters: [{ period: "3Q26", reported_net_debt_mbrl: null }],
  };
  const explanation = netCashUnavailableReason(report, valuation);
  assert.match(explanation ?? "", /3Q26/);
  assert.match(explanation ?? "", /2Q26/);
  assert.deepEqual(currentPeriodNetCash(report, valuation), {
    value: null, basis: "unavailable",
  });
});

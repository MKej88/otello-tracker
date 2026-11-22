import test from "node:test";
import assert from "node:assert/strict";
import { parseBrazilServerTiming, parseNavHistoryServerTiming, parseOtelloOriginTiming, parseWorkerFetchTiming, parseFxServerTiming } from "./server-timing.mjs";

test("reads only allow-listed server metrics", () => {
  const output = parseBrazilServerTiming(
    'brazil_handler;dur=25.2, brazil_d1;dur=20.1, brazil_parse;dur=1.2, brazil_snapshot;desc="stale", private;desc="secret"',
  );
  assert.deepEqual(output, { handlerMs: 25.2, d1Ms: 20.1, parseMs: 1.2, snapshot: "stale" });
  assert.equal(parseBrazilServerTiming('private;desc="secret"'), null);
  assert.equal(parseBrazilServerTiming(null), null);
  assert.doesNotMatch(JSON.stringify(output), /private|secret/);
});

test("origin timing parser is allow-listed and ignores private header values", () => {
  const sample = 'otello_handler;dur=81.23, otello_import;dur=17.5, otello_d1;dur=94.72, otello_reads;desc="15", private;desc="sensitive"';
  assert.deepEqual(parseOtelloOriginTiming(sample), {
    handlerMs: 81.23, importMs: 17.5, d1TotalMs: 94.72, d1Reads: 15,
  });
  assert.equal(parseOtelloOriginTiming('private;desc="sensitive"'), null);
  assert.equal(parseOtelloOriginTiming('otello_reads;desc="-2", otello_d1;dur=-1'), null);
  assert.equal(parseOtelloOriginTiming(null), null);
  assert.doesNotMatch(JSON.stringify(parseOtelloOriginTiming(sample)), /private|sensitive/);
  assert.deepEqual(parseOtelloOriginTiming('otello_snapshot;desc="hit"'), { snapshot: "hit" });
  assert.deepEqual(parseOtelloOriginTiming('otello_snapshot;desc="fallback"'), { snapshot: "fallback" });
  assert.equal(parseOtelloOriginTiming('otello_snapshot;desc="unknown"'), null);
});

test("Worker fetch timing exposes phase durations without unrelated header data", () => {
  const header = 'otello_fetch;dur=440.38, otello_asgi_import;dur=0.32, ' +
    'otello_asgi;dur=421.00, otello_fastapi;dur=230.50, ' +
    'otello_handler;dur=120.00, private;desc="customer details"';
  const result = parseWorkerFetchTiming(header);
  assert.deepEqual(result, {
    fetchMs: 440.38, asgiImportMs: 0.32,
    asgiMs: 421, fastapiMs: 230.5,
  });
  assert.doesNotMatch(JSON.stringify(result), /private|customer/);
  assert.equal(parseWorkerFetchTiming(null), null);
  assert.equal(parseWorkerFetchTiming("otello_asgi;dur=-10"), null);
  assert.equal(parseWorkerFetchTiming("otello_fetch;dur=not-a-number"), null);
  assert.deepEqual(parseWorkerFetchTiming("otello_fetch;dur=0.00"), { fetchMs: 0 });
});

test("request D1 timing exposes only bounded, allow-listed aggregates", () => {
  const header = 'otello_fetch;dur=240.00, otello_req_d1;dur=190.12, ' +
    'otello_req_reads;desc="8", secret;desc="customer-data"';
  const metrics = parseWorkerFetchTiming(header);
  assert.deepEqual(metrics, {
    fetchMs: 240, requestD1TotalMs: 190.12, requestD1Reads: 8,
  });
  assert.doesNotMatch(JSON.stringify(metrics), /secret|customer/);
  assert.equal(parseWorkerFetchTiming('otello_req_d1;dur=-10'), null);
  assert.equal(parseWorkerFetchTiming('otello_req_reads;desc="-2"'), null);
  assert.equal(parseWorkerFetchTiming('otello_req_reads;desc="123456"'), null);
});

test("NAV history diagnostics parse only fixed reasons, cache states and aggregate timings", () => {
  const header = 'navhist_cache;desc="fallback", navhist_reason;desc="date_mismatch", ' +
    'navhist_lookup;dur=23.17, navhist_fallback;dur=245.60, navhist_d1;dur=68.34, ' +
    'navhist_reads;desc="19", private;desc="financial payload"';
  const timing = parseNavHistoryServerTiming(header);
  assert.deepEqual(timing, {
    cache: "fallback", reason: "date_mismatch", lookupMs: 23.17,
    fallbackMs: 245.6, d1TotalMs: 68.34, d1Reads: 19,
  });
  assert.doesNotMatch(JSON.stringify(timing), /private|financial|payload/);
  assert.deepEqual(parseNavHistoryServerTiming('navhist_cache;desc="hit", navhist_reason;desc="none"'),
    { cache: "hit", reason: "none" });
  assert.equal(parseNavHistoryServerTiming('navhist_reason;desc="user-supplied"'), null);
  assert.equal(parseNavHistoryServerTiming('navhist_cache;desc="secret"'), null);
  assert.equal(parseNavHistoryServerTiming('navhist_d1;dur=-1'), null);
  assert.equal(parseNavHistoryServerTiming('navhist_d1;dur=NaN'), null);
  assert.equal(parseNavHistoryServerTiming(null), null);
});

test("FX parser stores only allow-listed aggregate phase timings", () => {
  const header = 'fx_handler;dur=760.23, fx_import;dur=0.01, fx_lookup;dur=70.20, ' +
    'fx_brl;dur=120.10, fx_usd;dur=130.40, fx_spot;dur=14.10, ' +
    'fx_compute;dur=8.50, fx_d1;dur=265.30, fx_reads;desc="4", ' +
    'secret;desc="private account information"';
  const parsed = parseFxServerTiming(header);
  assert.deepEqual(parsed, {
    handlerMs: 760.23, importMs: 0.01, lookupMs: 70.2,
    brlSeriesMs: 120.1, usdSeriesMs: 130.4, spotMs: 14.1,
    computeMs: 8.5, d1TotalMs: 265.3, d1Reads: 4,
  });
  assert.equal(parseFxServerTiming('secret;desc="private"'), null);
  assert.equal(parseFxServerTiming('fx_brl;dur=-1, fx_reads;desc="-2"'), null);
  assert.equal(parseFxServerTiming(null), null);
  assert.doesNotMatch(JSON.stringify(parsed), /secret|private/);
});

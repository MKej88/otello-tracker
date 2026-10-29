import test from "node:test";
import assert from "node:assert/strict";
import { parseBrazilServerTiming, parseOtelloOriginTiming, parseWorkerFetchTiming } from "./server-timing.mjs";

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

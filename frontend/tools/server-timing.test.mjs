import test from "node:test";
import assert from "node:assert/strict";
import { parseBrazilServerTiming, parseOtelloOriginTiming } from "./server-timing.mjs";

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

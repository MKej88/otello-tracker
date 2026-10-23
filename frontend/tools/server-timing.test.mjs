import test from "node:test";
import assert from "node:assert/strict";
import { parseBrazilServerTiming } from "./server-timing.mjs";

test("reads only allow-listed server metrics", () => {
  const output = parseBrazilServerTiming(
    'brazil_handler;dur=25.2, brazil_d1;dur=20.1, brazil_parse;dur=1.2, brazil_snapshot;desc="stale", private;desc="secret"',
  );
  assert.deepEqual(output, { handlerMs: 25.2, d1Ms: 20.1, parseMs: 1.2, snapshot: "stale" });
  assert.equal(parseBrazilServerTiming('private;desc="secret"'), null);
  assert.equal(parseBrazilServerTiming(null), null);
  assert.doesNotMatch(JSON.stringify(output), /private|secret/);
});

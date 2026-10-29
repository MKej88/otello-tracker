import test from "node:test";
import assert from "node:assert/strict";
import { channel } from "node:diagnostics_channel";
import { cloudflareColo, phaseDurations, watchUndiciRequest } from "./api-network-phases.mjs";

test("CF colo parsing is narrow and never leaks other header information", () => {
  assert.equal(cloudflareColo("8c921cab12345678-FRA"), "FRA");
  assert.equal(cloudflareColo("ff0123456789abcd-iad"), "IAD");
  assert.equal(cloudflareColo("secret-host-private"), null);
  assert.equal(cloudflareColo(null), null);
});

test("Transport phases stay separate from server computation, with safe missing values", () => {
  assert.deepEqual(phaseDurations({
    createdAt: 102, sentAt: 198.8, receivedAt: 1500.2,
  }, 100), { fetchToRequestMs: 2, requestToSendMs: 97, sendToHeadersMs: 1301 });
  assert.deepEqual(phaseDurations({
    createdAt: null, sentAt: null, receivedAt: null,
  }, 100), { fetchToRequestMs: null, requestToSendMs: null, sendToHeadersMs: null });
  assert.equal(phaseDurations({ createdAt: 20, sentAt: 10, receivedAt: 100 }, 1).requestToSendMs, null);
});

test("Undici events correlate by exact URL/path and unsubscribe", () => {
  const times = [101, 116, 250];
  const watch = watchUndiciRequest("https://otellotracker.com/api/bemobi/dashboard", () => times.shift());
  const target = { origin: "https://otellotracker.com", path: "/api/bemobi/dashboard" };
  const other = { origin: "https://example.com", path: "/api/bemobi/dashboard" };
  const alt = { origin: "https://otellotracker.com", path: "/api/health" };
  try {
    channel("undici:request:create").publish({ request: other });
    channel("undici:request:create").publish({ request: alt });
    channel("undici:request:create").publish({ request: target });
    channel("undici:client:sendHeaders").publish({ request: other });
    channel("undici:client:sendHeaders").publish({ request: target });
    channel("undici:request:headers").publish({ request: target });
    assert.deepEqual(watch.snapshot(100), {
      fetchToRequestMs: 1, requestToSendMs: 15, sendToHeadersMs: 134,
    });
  } finally {
    watch.close();
    watch.close();
  }
  assert.equal(channel("undici:request:create").hasSubscribers, false);
});

test("Missing Undici events return null phases, not false fast timings", () => {
  const w = watchUndiciRequest("https://otellotracker.com/api/health");
  try {
    assert.deepEqual(w.snapshot(0), {
      fetchToRequestMs: null, requestToSendMs: null, sendToHeadersMs: null,
    });
  } finally { w.close(); }
});

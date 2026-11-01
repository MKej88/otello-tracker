import assert from "node:assert/strict";
import { test } from "node:test";
import {
  readShortLivedResource,
  retainShortLivedResource,
} from "../src/shortLivedResourceCache.ts";

const values = new Map<string, string>();
const storage = {
  getItem: (key: string) => values.get(key) ?? null,
  setItem: (key: string, value: string) => { values.set(key, value); },
  removeItem: (key: string) => { values.delete(key); },
};
Object.assign(globalThis, { window: { sessionStorage: storage } });

test("FX last-good response is rendered immediately for at most two minutes", () => {
  const url = "/api/fx/dashboard";
  const result = { ready: true, as_of_date: "2026-11-01", rate: 1.72 };
  retainShortLivedResource(url, result, 1_000_000);
  assert.deepEqual(readShortLivedResource(url, 1_000_001), result);
  assert.deepEqual(readShortLivedResource(url, 1_119_999), result);
  assert.equal(readShortLivedResource(url, 1_120_001), null);
});

test("technical status is not reused past 10 seconds", () => {
  const url = "/api/dashboard/runtime-status";
  retainShortLivedResource(url, { ready: true, status: "OK" }, 2_000_000);
  assert.deepEqual(readShortLivedResource(url, 2_005_000), { ready: true, status: "OK" });
  assert.equal(readShortLivedResource(url, 2_011_000), null);
});

test("unready, failed or unrelated sensitive market responses never enter this cache", () => {
  const url = "/api/fx/dashboard";
  retainShortLivedResource(url, { ready: false }, 3_000_000);
  assert.equal(readShortLivedResource(url, 3_000_001), null);
  retainShortLivedResource("/api/market/quotes", { ready: true, price: 20 }, 3_000_000);
  retainShortLivedResource("/api/dashboard/economic", { ready: true, nav: 40 }, 3_000_000);
  assert.equal(readShortLivedResource("/api/market/quotes", 3_000_001), null);
  assert.equal(readShortLivedResource("/api/dashboard/economic", 3_000_001), null);
});

test("unavailable sessionStorage still permits short in-memory reuse", () => {
  Object.assign(globalThis, { window: { get sessionStorage() { throw new Error("blocked"); } } });
  const url = "/api/fx/dashboard";
  const result = { ready: true, as_of_date: "2026-11-01", rate: 1.73 };
  retainShortLivedResource(url, result, 4_000_000);
  assert.deepEqual(readShortLivedResource(url, 4_000_001), result);
});

test("future timestamps are rejected so an inaccurate clock cannot pin old data", () => {
  retainShortLivedResource("/api/fx/dashboard", { ready: true }, 5_000_000);
  assert.equal(readShortLivedResource("/api/fx/dashboard", 4_999_999), null);
});

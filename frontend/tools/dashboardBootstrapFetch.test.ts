import assert from "node:assert/strict";
import test from "node:test";

const completePayload = (label: string) => ({
  summary: { label },
  economic: { label },
  quotes: { label },
  buyback: { label },
  events: { label },
});

test("leverer nettverksoppdatering selv om den blir ferdig før lytteren monteres", async () => {
  const cachedPayload = completePayload("gammel");
  const freshPayload = completePayload("fersk");
  const storage = new Map<string, string>([
    [
      "otello.dashboard.bootstrap.v3",
      JSON.stringify({ cacheVersion: 3, storedAt: Date.now(), payload: cachedPayload }),
    ],
  ]);
  const networkRequests: RequestInit[] = [];

  const fakeWindow = {
    location: { origin: "https://otello.test" },
    localStorage: {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => storage.set(key, value),
      removeItem: (key: string) => storage.delete(key),
    },
    setTimeout,
    clearTimeout,
    fetch: async (_input: RequestInfo | URL, init?: RequestInit) => {
      networkRequests.push(init ?? {});
      return Response.json(freshPayload);
    },
  };
  Object.assign(globalThis, { window: fakeWindow });

  const bootstrap = await import("../src/dashboardBootstrapFetch.ts");
  bootstrap.installDashboardBootstrapFetch();

  const cachedResponse = await fakeWindow.fetch("/api/dashboard/summary");
  assert.deepEqual(await cachedResponse.json(), cachedPayload.summary);

  // Let the already-started network request publish before subscribing. This
  // reproduces the race that previously left the old NAV visible.
  await new Promise((resolve) => setTimeout(resolve, 0));

  let received: unknown = null;
  bootstrap.subscribeDashboardRevalidation("/api/dashboard/summary", (value) => {
    received = value;
  });

  assert.deepEqual(received, freshPayload.summary);
  // Standard cache semantics keep this request compatible with index.html's
  // fetch preload, while the request still publishes its fresh response.
  assert.equal(networkRequests[0]?.cache, undefined);
});


const CACHE_KEY = "otello.dashboard.bootstrap.v3";
const SEVEN_DAYS = 7 * 24 * 60 * 60 * 1000;

async function isolatedBootstrap(name: string, storedAt: number, payload: unknown, now: () => number) {
  const storage = new Map<string, string>([[CACHE_KEY, JSON.stringify({cacheVersion: 3, storedAt, payload})]]);
  const requests: string[] = [];
  const fakeWindow = {
    location: { origin: "https://otello.test" },
    localStorage: {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => storage.set(key, value),
      removeItem: (key: string) => storage.delete(key),
    },
    setTimeout, clearTimeout,
    fetch: async (input: RequestInfo | URL, _init?: RequestInit) => {
      const path = String(input);
      requests.push(path);
      return path === "/api/dashboard/bootstrap"
        ? Response.json(completePayload("bootstrap"))
        : Response.json({label: "direkte", at: now()});
    },
  };
  Object.assign(globalThis, { window: fakeWindow });
  const module = await import(new URL(`../src/dashboardBootstrapFetch.ts?case=${name}`, import.meta.url).href);
  return {module, fakeWindow, requests, storage};
}

test("bootstrap rejects future timestamps and array components", async (t) => {
  const now = 1_800_000_000_000;
  t.mock.method(Date, "now", () => now);
  const future = await isolatedBootstrap("future", now + 1, completePayload("framtid"), () => now);
  assert.equal(future.module.getCachedDashboardComponent("summary"), null);
  assert.equal(future.storage.has(CACHE_KEY), false);
  const array = await isolatedBootstrap("array", now, {...completePayload("ugyldig"), quotes: []}, () => now);
  assert.equal(array.module.getCachedDashboardComponent("summary"), null);
  assert.equal(array.storage.has(CACHE_KEY), false);
});

test("memoized browser bootstrap expires at its existing seven-day boundary", async (t) => {
  let now = 1_800_000_000_000;
  t.mock.method(Date, "now", () => now);
  const {module} = await isolatedBootstrap("expiry", now - SEVEN_DAYS, completePayload("sist god"), () => now);
  assert.deepEqual(module.getCachedDashboardComponent("summary"), {label: "sist god"});
  now += 1;
  assert.equal(module.getCachedDashboardComponent("summary"), null);
});

test("late first component request and explicit refresh bypass startup bootstrap", async (t) => {
  let now = 1_800_000_000_000;
  t.mock.method(Date, "now", () => now);
  const {module, fakeWindow, requests} = await isolatedBootstrap("late", now, completePayload("gammel"), () => now);
  module.installDashboardBootstrapFetch();
  const forced = await fakeWindow.fetch("/api/dashboard/summary", {cache: "no-store"});
  assert.equal((await forced.json()).label, "direkte");
  const subsequent = await fakeWindow.fetch("/api/dashboard/summary");
  assert.equal((await subsequent.json()).label, "direkte");
  const crossOrigin = await fakeWindow.fetch("https://other.test/api/market/quotes");
  assert.equal((await crossOrigin.json()).label, "direkte");
  now += 30_001;
  const late = await fakeWindow.fetch("/api/market/quotes");
  assert.equal((await late.json()).label, "direkte");
  assert.deepEqual(requests, ["/api/dashboard/bootstrap", "/api/dashboard/summary",
    "/api/dashboard/summary", "https://other.test/api/market/quotes", "/api/market/quotes"]);
});

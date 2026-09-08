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
  assert.equal(networkRequests[0]?.cache, "no-cache");
});

import assert from "node:assert/strict";
import test from "node:test";

const completePayload = (price: number) => ({
  summary: { price },
  economic: { price },
  quotes: { price },
  buyback: { price },
  events: { price },
});

test("fersk bootstrap erstatter gammel navigasjonscache og ventende cachesvar", async () => {
  const oldPayload = completePayload(8);
  const freshPayload = completePayload(10);
  const storage = new Map([
    ["otello.dashboard.bootstrap.v3", JSON.stringify({
      cacheVersion: 3, storedAt: Date.now(), payload: oldPayload,
    })],
  ]);
  let releaseBootstrap!: () => void;
  const bootstrapReady = new Promise<void>((resolve) => { releaseBootstrap = resolve; });
  const fakeWindow = {
    location: { origin: "https://otello.test" },
    localStorage: {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => storage.set(key, value),
      removeItem: (key: string) => storage.delete(key),
    },
    setTimeout,
    clearTimeout,
    fetch: async (_input: RequestInfo | URL, _init?: RequestInit) => {
      await bootstrapReady;
      return Response.json(freshPayload);
    },
  };
  const originalWindow = globalThis.window;
  const originalFetch = globalThis.fetch;
  Object.assign(globalThis, { window: fakeWindow });
  globalThis.fetch = (...args) => fakeWindow.fetch(...args);

  let unsubscribe: (() => void) | null = null;
  try {
    const bootstrap = await import("../src/dashboardBootstrapFetch.ts");
    const preload = await import("../src/navigationDataPreload.ts");
    bootstrap.installDashboardBootstrapFetch();
    const url = "/api/dashboard/summary";
    assert.deepEqual(await preload.fetchPreloadedJson(url), oldPayload.summary);

    // Keep another cached response in flight while the network revalidates.
    const quotesUrl = "/api/market/quotes";
    const cachedQuotes = await fakeWindow.fetch(quotesUrl);
    let releaseQuotes!: () => void;
    const quotesReady = new Promise<void>((resolve) => { releaseQuotes = resolve; });
    const wrappedFetch = fakeWindow.fetch;
    globalThis.fetch = async (...args) => {
      if (args[0] === quotesUrl) {
        await quotesReady;
        return cachedQuotes;
      }
      return wrappedFetch(...args);
    };
    const pendingQuotes = preload.fetchPreloadedJson(quotesUrl);
    let updated: unknown = null;
    unsubscribe = bootstrap.subscribeDashboardRevalidation(url, (value) => { updated = value; });
    releaseBootstrap();
    await new Promise((resolve) => setTimeout(resolve, 0));
    releaseQuotes();
    const quotes = await pendingQuotes;

    assert.deepEqual(updated, freshPayload.summary);
    // A remounted polling hook reads this cache after receiving revalidation.
    assert.deepEqual(await preload.fetchPreloadedJson(url), freshPayload.summary);
    assert.deepEqual(quotes, freshPayload.quotes);
    assert.deepEqual(await preload.fetchPreloadedJson(quotesUrl), freshPayload.quotes);
  } finally {
    unsubscribe?.();
    globalThis.fetch = originalFetch;
    Object.assign(globalThis, { window: originalWindow });
  }
});

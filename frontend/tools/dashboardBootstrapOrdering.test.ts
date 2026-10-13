import assert from "node:assert/strict";
import test from "node:test";

const payload = (price: number, observedAt: string) => ({
  summary: { otec_price: price, otec_price_updated_at: observedAt },
  economic: { calculated_at: observedAt },
  quotes: { symbols: { OTEC: { last: price, last_updated_at: observedAt } } },
  buyback: {},
  events: {},
});

test("bootstrap kan ikke rulle tilbake en fullført nyere polling", async (t) => {
  const cached = payload(8, "2026-10-09T13:00:00Z");
  const bootstrapValue = payload(9, "2026-10-09T13:30:00Z");
  const polled = payload(10, "2026-10-09T14:00:00Z");
  const url = "/api/dashboard/summary";
  const originalWindow = globalThis.window;
  let scenario = 0;

  for (const timing of ["late", "replay", "queued", "failed"] as const) {
    await t.test(timing, async () => {
      let finishBootstrap!: (response: Response) => void;
      const bootstrapResponse = new Promise<Response>((resolve) => { finishBootstrap = resolve; });
      const queued: Array<() => void> = [];
      const fakeWindow = {
        location: { origin: "https://otello.test" },
        localStorage: {
          getItem: () => JSON.stringify({ cacheVersion: 3, storedAt: Date.now(), payload: cached }),
          setItem: () => undefined,
          removeItem: () => undefined,
        },
        setTimeout: (callback: () => void) => { queued.push(callback); return queued.length; },
        clearTimeout: () => undefined,
        fetch: async (input: RequestInfo | URL, _init?: RequestInit) => input === "/api/dashboard/bootstrap"
          ? bootstrapResponse
          : timing === "failed" ? new Response(null, { status: 503 }) : Response.json(polled.summary),
      };
      Object.assign(globalThis, { window: fakeWindow });
      // Each scenario gets an independent installation, as a new page load would.
      const bootstrap = await import(`../src/dashboardBootstrapFetch.ts?ordering=${scenario++}`);
      const flush = () => new Promise((resolve) => setTimeout(resolve, 0));
      const subscriptions: Array<() => void> = [];
      try {
        bootstrap.installDashboardBootstrapFetch();
        if (timing === "queued") {
          finishBootstrap(Response.json(bootstrapValue));
          await flush();
        }
        let displayed = await (await fakeWindow.fetch(url)).json();
        assert.deepEqual(displayed, cached.summary);
        subscriptions.push(bootstrap.subscribeDashboardRevalidation(url, (value: unknown) => { displayed = value; }));

        if (timing === "replay") {
          finishBootstrap(Response.json(bootstrapValue));
          await flush();
          assert.deepEqual(displayed, bootstrapValue.summary);
        }

        // The next two-minute poll (or page-resume refresh) returns a newer source observation.
        const response = await fakeWindow.fetch(url);
        if (response.ok) displayed = await response.json();
        if (timing === "late" || timing === "failed") {
          finishBootstrap(Response.json(bootstrapValue));
          await flush();
        }
        for (const callback of queued) callback();

        const expected = timing === "failed" ? bootstrapValue.summary : polled.summary;
        assert.deepEqual(displayed, expected, "et eldre oppstartssvar må ikke overskrive nyere markedsdata");

        // Navigating back must not replay the superseded startup response either.
        subscriptions.push(bootstrap.subscribeDashboardRevalidation(url, (value: unknown) => { displayed = value; }));
        assert.deepEqual(displayed, expected, "remontering må ikke gjeninnføre oppstartsdata");

        // A successful summary poll must not suppress revalidation of other components.
        await fakeWindow.fetch("/api/market/quotes");
        let quotes: unknown;
        subscriptions.push(bootstrap.subscribeDashboardRevalidation("/api/market/quotes", (value: unknown) => { quotes = value; }));
        assert.deepEqual(quotes, bootstrapValue.quotes);
      } finally {
        subscriptions.forEach((unsubscribe) => unsubscribe?.());
        Object.assign(globalThis, { window: originalWindow });
      }
    });
  }
});

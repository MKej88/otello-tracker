import assert from "node:assert/strict";
import test from "node:test";

test("prioriterer synlig NAV-periode før bunten med øvrige perioder", async () => {
  const requests: string[] = [];
  let releaseInitial: (() => void) | undefined;
  const initialReady = new Promise<void>((resolve) => {
    releaseInitial = resolve;
  });

  Object.assign(globalThis, {
    fetch: async (input: RequestInfo | URL) => {
      const url = String(input);
      requests.push(url);
      if (url === "/api/initial") await initialReady;
      return Response.json(
        url === "/api/dashboard/nav-periods"
          ? { ready: true, periods: { later: { ready: true } } }
          : { estimated: { ready: true, period: "initial" } },
      );
    },
  });

  const preload = await import("../src/navigationDataPreload.ts");
  preload.preloadNavPeriodBundle(
    { initial: "/api/initial", later: "/api/later" },
    "initial",
  );
  const visiblePeriod = preload.fetchPreloadedJson<{ estimated: { period: string } }>(
    "/api/initial",
  );

  assert.deepEqual(requests, ["/api/initial"]);
  releaseInitial?.();
  assert.equal((await visiblePeriod).estimated.period, "initial");
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.deepEqual(requests, ["/api/initial", "/api/dashboard/nav-periods"]);
});

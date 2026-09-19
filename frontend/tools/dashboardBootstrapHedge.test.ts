import assert from "node:assert/strict";
import test from "node:test";

test("starter dedikert endepunkt når bootstrap bruker for lang tid", async () => {
  let releaseBootstrap: ((value: Response) => void) | undefined;
  const blockedBootstrap = new Promise<Response>((resolve) => {
    releaseBootstrap = resolve;
  });
  const requests: string[] = [];
  const fakeWindow = {
    location: { origin: "https://otello.test" },
    localStorage: {
      getItem: () => null,
      setItem: () => undefined,
      removeItem: () => undefined,
    },
    setTimeout,
    clearTimeout,
    fetch: async (input: RequestInfo | URL) => {
      const url = String(input);
      requests.push(url);
      if (url === "/api/dashboard/bootstrap") return blockedBootstrap;
      return Response.json({ ready: true, source: "dedikert" });
    },
  };
  Object.assign(globalThis, { window: fakeWindow });

  const bootstrap = await import("../src/dashboardBootstrapFetch.ts");
  bootstrap.installDashboardBootstrapFetch();

  const response = await fakeWindow.fetch("/api/dashboard/summary");
  assert.deepEqual(await response.json(), { ready: true, source: "dedikert" });
  assert.deepEqual(requests, [
    "/api/dashboard/bootstrap",
    "/api/dashboard/summary",
  ]);

  releaseBootstrap?.(Response.json({}));
});

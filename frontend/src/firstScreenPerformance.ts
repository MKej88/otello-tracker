/** Small, browser-local measurements. No beacons, cookies or personal data. */
export type TimedApi = { path: string; durationMs: number };
export type FirstScreenSample = {
  route: "Oversikt" | "Brasil";
  recordedAt: string;
  firstDataMs: number;
  ttfbMs: number | null;
  domReadyMs: number | null;
  slowApi: TimedApi[];
};

export type FirstScreenStats = {
  count: number;
  medianMs: number | null;
  p95Ms: number | null;
  medianTtfbMs: number | null;
  latest: FirstScreenSample | null;
};

const STORAGE_KEY = "otello.performance.first-screen.v1";
const MAX_SAMPLES = 40;
let entryView: string | null = null;
let alreadyRecorded = false;

function roundedMs(value: number | undefined | null): number | null {
  return typeof value === "number" && Number.isFinite(value) && value >= 0
    ? Math.round(value)
    : null;
}

export function initializeFirstScreenTiming(view: string): void {
  if (entryView == null) entryView = view;
}

export function readFirstScreenSamples(): FirstScreenSample[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    const saved: unknown = raw ? JSON.parse(raw) : null;
    if (!Array.isArray(saved)) return [];
    return saved.filter((item): item is FirstScreenSample =>
      item != null && typeof item === "object"
      && (item.route === "Oversikt" || item.route === "Brasil")
      && typeof item.recordedAt === "string"
      && typeof item.firstDataMs === "number"
      && Number.isFinite(item.firstDataMs) && item.firstDataMs >= 0
      && Array.isArray(item.slowApi)
    ).slice(-MAX_SAMPLES);
  } catch {
    return [];
  }
}

function percentile(values: number[], share: number): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const index = Math.ceil(sorted.length * share) - 1;
  return sorted[Math.max(0, index)] ?? null;
}

export function summarizeFirstScreen(
  samples: FirstScreenSample[],
  route: FirstScreenSample["route"],
): FirstScreenStats {
  const matching = samples.filter((sample) => sample.route === route);
  const ttfb = matching.flatMap((sample) => sample.ttfbMs == null ? [] : [sample.ttfbMs]);
  return {
    count: matching.length,
    medianMs: percentile(matching.map((sample) => sample.firstDataMs), 0.5),
    p95Ms: percentile(matching.map((sample) => sample.firstDataMs), 0.95),
    medianTtfbMs: percentile(ttfb, 0.5),
    latest: matching.at(-1) ?? null,
  };
}

export function slowestApiResources(
  entries: Array<Pick<PerformanceResourceTiming, "name" | "duration">>,
  origin: string,
): TimedApi[] {
  return entries.flatMap((entry) => {
    try {
      const uri = new URL(entry.name);
      if (uri.origin !== origin || !uri.pathname.startsWith("/api/")) return [];
      const durationMs = roundedMs(entry.duration);
      // Never store URL parameters, external domains or personal identifiers.
      return durationMs == null ? [] : [{ path: uri.pathname, durationMs }];
    } catch {
      return [];
    }
  }).sort((a, b) => b.durationMs - a.durationMs).slice(0, 3);
}

/** Measure only the page opened directly, not SPA navigation to a later view. */
export function recordFirstScreenReady(view: FirstScreenSample["route"]): void {
  if (typeof window === "undefined" || typeof performance === "undefined") return;
  if (alreadyRecorded || entryView !== view) return;
  alreadyRecorded = true;

  window.requestAnimationFrame(() => {
    if (document.visibilityState === "hidden") return;
    try {
      const navigation = performance.getEntriesByType("navigation")[0] as PerformanceNavigationTiming | undefined;
      const sample: FirstScreenSample = {
        route: view,
        recordedAt: new Date().toISOString(),
        firstDataMs: Math.round(performance.now()),
        ttfbMs: roundedMs(navigation?.responseStart),
        domReadyMs: roundedMs(navigation?.domContentLoadedEventEnd),
        slowApi: slowestApiResources(
          performance.getEntriesByType("resource") as PerformanceResourceTiming[],
          window.location.origin,
        ),
      };
      window.localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify([...readFirstScreenSamples(), sample].slice(-MAX_SAMPLES)),
      );
    } catch {
      // The site must always work when browser storage/timing APIs are restricted.
    }
  });
}

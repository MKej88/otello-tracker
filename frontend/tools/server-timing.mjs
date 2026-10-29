/** Only allow-listed, aggregate Brazil timings may enter performance artifacts. */
export function parseBrazilServerTiming(header) {
  if (!header) return null;
  const result = {};
  for (const metric of header.split(",")) {
    const duration = /^\s*brazil_(handler|d1|parse);dur=(\d+(?:\.\d{1,3})?)\s*$/.exec(metric);
    if (duration) {
      const key = duration[1] + "Ms";
      result[key] = Number(duration[2]);
      continue;
    }
    const snapshot = /^\s*brazil_snapshot;desc="(fresh|stale|missing|historical)"\s*$/.exec(metric);
    if (snapshot) result.snapshot = snapshot[1];
  }
  return Object.keys(result).length ? result : null;
}

/** Origin-only timings for Bemobi and buyback routes.
 * D1 is a sum of concurrent read durations, not exclusive wall-clock time.
 */
export function parseOtelloOriginTiming(header) {
  if (!header) return null;
  const result = {};
  for (const component of header.split(",")) {
    const metric = /^\s*otello_(handler|d1);dur=(\d+(?:\.\d{1,3})?)\s*$/.exec(component);
    if (metric) {
      result[metric[1] === "handler" ? "handlerMs" : "d1TotalMs"] = Number(metric[2]);
      continue;
    }
    const count = /^\s*otello_reads;desc="(\d{1,5})"\s*$/.exec(component);
    if (count) result.d1Reads = Number(count[1]);
  }
  return Object.keys(result).length ? result : null;
}

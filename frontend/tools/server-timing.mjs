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

/**
 * Correlation-only output for slow production probes.
 * Emits only fixed /api/ paths, validated CF Ray IDs (without the colo
 * suffix), UTC timestamps, cache status and measured duration.
 * Raw headers, URLs with query strings, and personal data are never logged.
 */
export function slowTraceCandidates(api, thresholdMs = 1500) {
  const rows = [];
  for (const probe of api || []) {
    const pathname = String(probe?.endpoint || "").split("?")[0];
    if (!/^\/api\/[a-z0-9/_-]+$/i.test(pathname)) continue;
    for (let i = 0; i < (probe.sampleTotalMs?.length || 0); i++) {
      const elapsedMs = probe.sampleTotalMs[i];
      if (!Number.isFinite(elapsedMs) || elapsedMs < thresholdMs) continue;
      const match = /^([0-9a-f]{8,32})-([a-z]{3})$/i.exec(probe.cfRay?.[i] || "");
      const utc = probe.sampleStartedAt?.[i];
      const validUtc = typeof utc === "string" &&
        /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/.test(utc) ? utc : null;
      const cache = probe.cfCacheStatus?.[i];
      rows.push({
        path: pathname,
        elapsedMs: Math.round(elapsedMs),
        utc: validUtc,
        rayId: match ? match[1].toLowerCase() : null,
        colo: match ? match[2].toUpperCase() : null,
        cache: ["MISS", "HIT", "BYPASS"].includes(cache) ? cache : "unknown",
      });
    }
  }
  return rows;
}

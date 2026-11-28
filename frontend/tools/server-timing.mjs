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
    const metric = /^\s*otello_(handler|d1|import);dur=(\d+(?:\.\d{1,3})?)\s*$/.exec(component);
    if (metric) {
      const name = { handler: "handlerMs", d1: "d1TotalMs", import: "importMs" }[metric[1]];
      result[name] = Number(metric[2]);
      continue;
    }
    const count = /^\s*otello_reads;desc="(\d{1,5})"\s*$/.exec(component);
    if (count) result.d1Reads = Number(count[1]);
    const source = /^\s*otello_snapshot;desc="(hit|fallback)"\s*$/.exec(component);
    if (source) result.snapshot = source[1];
  }
  return Object.keys(result).length ? result : null;
}

/**
 * Python Worker and ASGI entry durations for all API routes.
 * These timers start after Cloudflare has entered Python Default.fetch:
 * they do not measure isolate startup before Python or the network RTT.
 */
export function parseWorkerFetchTiming(header) {
  if (!header) return null;
  const result = {};
  const allowed = {
    otello_fetch: "fetchMs",
    otello_asgi_import: "asgiImportMs",
    otello_asgi: "asgiMs",
    otello_fastapi: "fastapiMs",
    otello_req_d1: "requestD1TotalMs",
  };
  for (const part of header.split(",")) {
    const match = /^\s*(otello_fetch|otello_asgi_import|otello_asgi|otello_fastapi|otello_req_d1);dur=(\d+(?:\.\d{1,3})?)\s*$/.exec(part);
    if (match) result[allowed[match[1]]] = Number(match[2]);
    const count = /^\s*otello_req_reads;desc="(\d{1,5})"\s*$/.exec(part);
    if (count) result.requestD1Reads = Number(count[1]);
    const coverage = /^\s*otello_req_row_meta;desc="(\d{1,5})\/(\d{1,5})"\s*$/.exec(part);
    if (coverage && Number(coverage[1]) <= Number(coverage[2])) {
      result.requestD1MetaObserved = Number(coverage[1]);
      result.requestD1MetaOperations = Number(coverage[2]);
    }
    const rows = /^\s*otello_req_rows_read;desc="(\d{1,12})"\s*$/.exec(part);
    if (rows) result.requestD1RowsRead = Number(rows[1]);
  }
  if (!(result.requestD1MetaOperations > 0 && result.requestD1MetaObserved === result.requestD1MetaOperations)) {
    delete result.requestD1RowsRead;
  }
  return Object.keys(result).length ? result : null;
}

 
/** Only fixed NAV-history cache states and aggregate durations are reportable. */
export function parseNavHistoryServerTiming(header) {
  if (!header) return null;
  const result = {};
  const timingNames = {
    lookup: "lookupMs", fallback: "fallbackMs", d1: "d1TotalMs",
  };
  for (const component of header.split(",")) {
    const metric = /^\s*navhist_(lookup|fallback|d1);dur=(\d+(?:\.\d{1,3})?)\s*$/.exec(component);
    if (metric) {
      result[timingNames[metric[1]]] = Number(metric[2]);
      continue;
    }
    const cache = /^\s*navhist_cache;desc="(hit|fallback)"\s*$/.exec(component);
    if (cache) {
      result.cache = cache[1];
      continue;
    }
    const reason = /^\s*navhist_reason;desc="(none|non_preset|no_history|missing_entry|date_mismatch|version_mismatch)"\s*$/.exec(component);
    if (reason) {
      result.reason = reason[1];
      continue;
    }
    const reads = /^\s*navhist_reads;desc="(\d{1,5})"\s*$/.exec(component);
    if (reads) result.d1Reads = Number(reads[1]);
  }
  return Object.keys(result).length ? result : null;
}

/** Allow-listed FX phase timings. The parallel phases must not be summed. */
export function parseFxServerTiming(header) {
  if (!header) return null;
  const names = {
    handler: "handlerMs", import: "importMs", lookup: "lookupMs",
    brl: "brlSeriesMs", usd: "usdSeriesMs", spot: "spotMs",
    compute: "computeMs", d1: "d1TotalMs",
  };
  const result = {};
  for (const part of header.split(",")) {
    const match = /^\s*fx_(handler|import|lookup|brl|usd|spot|compute|d1);dur=(\d+(?:\.\d{1,3})?)\s*$/.exec(part);
    if (match) result[names[match[1]]] = Number(match[2]);
    const reads = /^\s*fx_reads;desc="(\d{1,5})"\s*$/.exec(part);
    if (reads) result.d1Reads = Number(reads[1]);
  }
  return Object.keys(result).length ? result : null;
}

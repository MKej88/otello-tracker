/**
 * Small, explicit last-good cache for slow first-screen responses.
 *
 * This only avoids an empty loading screen on repeated visits within the same
 * browser tab. Every mounted consumer still requests fresh data immediately.
 * Do not cache NAV, live share prices, or failed/degraded responses here.
 */
const MAX_AGE_MS: Readonly<Record<string, number>> = {
  "/api/fx/dashboard": 2 * 60_000,
  "/api/dashboard/runtime-status": 10_000,
};
const KEY_PREFIX = "otello.short-lived-response.v1:";
const MAX_STORED_CHARS = 256_000;

type CacheEntry = { savedAt: number; value: Record<string, unknown> };
const memory = new Map<string, CacheEntry>();

function ttlFor(url: string): number | null {
  return Object.prototype.hasOwnProperty.call(MAX_AGE_MS, url) ? MAX_AGE_MS[url] : null;
}

function session(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.sessionStorage;
  } catch {
    // Private browsing or a locked-down device may prohibit storage.
    return null;
  }
}

function valid(entry: unknown, now: number, ttl: number): entry is CacheEntry {
  if (entry == null || typeof entry !== "object") return false;
  const data = entry as Partial<CacheEntry>;
  return typeof data.savedAt === "number"
    && Number.isFinite(data.savedAt)
    && data.savedAt <= now
    && now - data.savedAt <= ttl
    && data.value != null
    && typeof data.value === "object"
    && !Array.isArray(data.value)
    && data.value.ready === true;
}

export function readShortLivedResource<T>(url: string, now = Date.now()): T | null {
  const ttl = ttlFor(url);
  if (ttl == null) return null;

  const cached = memory.get(url);
  if (valid(cached, now, ttl)) return cached.value as T;
  memory.delete(url);

  const storage = session();
  if (!storage) return null;
  try {
    const raw = storage.getItem(KEY_PREFIX + url);
    if (raw == null) return null;
    const parsed: unknown = JSON.parse(raw);
    if (!valid(parsed, now, ttl)) {
      storage.removeItem(KEY_PREFIX + url);
      return null;
    }
    memory.set(url, parsed);
    return parsed.value as T;
  } catch {
    return null;
  }
}

export function retainShortLivedResource(url: string, value: unknown, now = Date.now()): void {
  if (ttlFor(url) == null || !valid({ savedAt: now, value }, now, 1)) return;
  const entry: CacheEntry = { savedAt: now, value: value as Record<string, unknown> };
  memory.set(url, entry);

  const storage = session();
  if (!storage) return;
  try {
    const raw = JSON.stringify(entry);
    if (raw.length <= MAX_STORED_CHARS) {
      storage.setItem(KEY_PREFIX + url, raw);
    }
  } catch {
    // Memory-only caching remains available if quota or storage access fails.
  }
}

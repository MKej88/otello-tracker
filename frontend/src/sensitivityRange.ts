/** Evenly spaced scenario values spanning the observed range, including the current quote. */
export function historicalScenarioRange(
  low: number | null | undefined,
  high: number | null | undefined,
  current: number,
  count: number,
): number[] {
  if (low == null || high == null || !Number.isFinite(low) || !Number.isFinite(high)
    || low <= 0 || high < low || !Number.isFinite(current) || current <= 0 || count < 2) return [];
  const from = Math.min(low, current);
  const to = Math.max(high, current);
  if (from === to) return [];
  const values = Array.from({ length: count }, (_, index) =>
    Number((from + (to - from) * index / (count - 1)).toFixed(4)));
  return new Set(values).size === count ? values : [];
}

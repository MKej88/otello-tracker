export type Quote = {
  ready: boolean;
  symbol: string;
  currency?: string | null;
  source?: string | null;
  last?: number | null;
  last_updated_at?: string | null;
  trading_date?: string | null;
  changes?: {
    daily_pct?: number | null;
    month_pct?: number | null;
    three_month_pct?: number | null;
  };
  volume?: {
    latest_date?: string | null;
    relative_3m?: number | null;
  };
  range_52w?: { low?: number | null; high?: number | null };
};

export type MarketQuotePayload = { ready: boolean; symbols?: Record<string, Quote> };

export function rangePosition(
  current?: number | null,
  low?: number | null,
  high?: number | null,
) {
  if (
    current == null
    || low == null
    || high == null
    || !Number.isFinite(current)
    || !Number.isFinite(low)
    || !Number.isFinite(high)
    || high < low
  ) return null;
  if (high === low) return 50;
  return Math.max(0, Math.min(100, ((current - low) / (high - low)) * 100));
}

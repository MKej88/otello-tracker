import type { NextQuarterEstimate } from "./nextQuarterConsensus";

export type ReportedQuarter = {
  period: string;
  source_name?: string | null;
  source_url?: string | null;
  source_page?: number | null;
  published_date?: string | null;
  source_evidence?: string | null;
  metrics: NextQuarterEstimate[];
};

export function compareQuarterMetric(estimate: NextQuarterEstimate, quarter?: ReportedQuarter | null) {
  const isAmount = Number.isFinite(estimate.value_mbrl);
  const isPercent = Number.isFinite(estimate.value_pct);
  if (isAmount === isPercent) return { actual: null, change: null, isPercent };
  const field = isAmount ? "value_mbrl" : "value_pct";
  const otherField = isAmount ? "value_pct" : "value_mbrl";
  const actualMetric = quarter?.metrics.find((metric) => metric.metric === estimate.metric && Number.isFinite(metric[field]) && !Number.isFinite(metric[otherField]));
  const actual = actualMetric?.[field] ?? null;
  const expected = estimate[field]!;
  const change = actual == null ? null : isPercent ? expected - actual : actual === 0 ? null : (expected / actual - 1) * 100;
  return { actual, change: Number.isFinite(change) ? change : null, isPercent };
}

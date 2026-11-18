/** Presentation-only Bemobi KPI helpers. The source report always wins. */
export type BemobiKpiSource = {
  period?: string | null;
  adjusted_ebitda_margin_pct?: number | null;
  adjusted_ebitda_mbrl?: number | null;
  adjusted_net_revenue_mbrl?: number | null;
};

export function kpiResultPeriod(result: BemobiKpiSource | null | undefined): string {
  return result?.period?.trim() || "Periode ukjent";
}

export function resolveAdjustedEbitdaMargin(
  result: BemobiKpiSource | null | undefined,
): { value: number | null; basis: "reported" | "calculated" | "missing" } {
  const reported = result?.adjusted_ebitda_margin_pct;
  if (reported != null && Number.isFinite(reported) && reported >= 0 && reported <= 100) {
    return { value: reported, basis: "reported" };
  }

  const revenue = result?.adjusted_net_revenue_mbrl;
  const ebitda = result?.adjusted_ebitda_mbrl;
  if (
    revenue != null && Number.isFinite(revenue) && revenue > 0
    && ebitda != null && Number.isFinite(ebitda)
    && ebitda >= 0 && ebitda <= revenue
  ) {
    return { value: ebitda / revenue * 100, basis: "calculated" };
  }
  return { value: null, basis: "missing" };
}

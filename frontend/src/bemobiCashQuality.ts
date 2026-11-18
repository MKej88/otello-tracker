/** Source-aware risk gates for Bemobi Cash-page calculations. */

export type ReportedBemobiCash = {
  period?: string | null;
  cash_mbrl?: number | null;
  cash_quality?: string | null;
};
export type BemobiValuationNetCash = {
  net_cash_mbrl?: number | null;
  ev_anchor_period?: string | null;
  source_quarters?: Array<{
    period?: string | null;
    reported_net_debt_mbrl?: number | null;
  }>;
};
export type BemobiDistribution = {
  type?: string | null;
  announcement_date?: string | null;
  ex_date?: string | null;
  gross_total_mbrl?: number | null;
  source_url?: string | null;
};

export function verifiedReportedCash(result: ReportedBemobiCash | null | undefined): number | null {
  const amount = result?.cash_mbrl;
  // This is a *validation gate*, not a replacement estimate. 2025/2026
  // mistakenly parsed as cash must never reach look-through or interest cards.
  if (
    amount == null || !Number.isFinite(amount) || amount < 10 || amount > 1500
    || result?.cash_quality === "REJECTED_IMPLAUSIBLE_CASH"
  ) return null;
  return amount;
}

export function currentPeriodNetCash(
  result: ReportedBemobiCash | null | undefined,
  valuation: BemobiValuationNetCash | null | undefined,
): { value: number | null; basis: "reported_quarter" | "current_anchor" | "unavailable" } {
  const period = result?.period?.trim();
  const cash = verifiedReportedCash(result);
  if (!period || cash == null) return { value: null, basis: "unavailable" };

  const currentReportedQuarter = valuation?.source_quarters?.find((item) => item.period === period);
  const reportedDebt = currentReportedQuarter?.reported_net_debt_mbrl;
  if (reportedDebt != null && Number.isFinite(reportedDebt)) {
    const net = -reportedDebt;
    if (net >= 0 && net <= cash) return { value: net, basis: "reported_quarter" };
  }
  const anchorNet = valuation?.net_cash_mbrl;
  if (
    valuation?.ev_anchor_period === period
    && anchorNet != null && Number.isFinite(anchorNet)
    && anchorNet >= 0 && anchorNet <= cash
  ) return { value: anchorNet, basis: "current_anchor" };
  return { value: null, basis: "unavailable" };
}

export function reportedQ3Jcp(distribution: BemobiDistribution | null | undefined): number | null {
  const gross = distribution?.gross_total_mbrl;
  // Q3 2026 announcement/ex-date falls in Q4 2026, following 30 Sep results.
  // Read confirmed corporate actions, never the older 16.19m TJLP projection.
  if (
    distribution?.type !== "JCP"
    || !distribution?.announcement_date?.startsWith("2026-11-")
    || !distribution?.ex_date?.startsWith("2026-11-")
    || gross == null || !Number.isFinite(gross) || gross <= 0 || gross >= 200
  ) return null;
  return gross;
}

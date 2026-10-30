export type NextQuarterEstimate = {
  metric: string;
  label: string;
  value_mbrl?: number;
  value_pct?: number;
  broker?: string | null;
  source_url?: string | null;
  published_date?: string | null;
  verified_date?: string | null;
  source_evidence?: string | null;
};

export type QuarterColumn = {
  key: string;
  metric: string;
  label: string;
  unit: "mbrl" | "pct";
};

export type QuarterBrokerRow = {
  broker: string;
  publishedDate: string | null;
  verifiedDate: string | null;
  sourceEvidence: string | null;
  sourceUrls: string[];
  values: Record<string, { value: number; derived: boolean; derivation?: string }>; 
};

export const MAIN_QUARTER_METRICS = [
  "revenue_mbrl", "adjusted_ebitda_mbrl", "adjusted_net_income_mbrl", "ebitda_margin_pct",
];

export function buildNextQuarterConsensus(estimates: NextQuarterEstimate[]) {
  const grouped = new Map<string, { broker: string; estimates: NextQuarterEstimate[] }>();
  for (const estimate of estimates) {
    const broker = estimate.broker?.trim() || "Meglerhus";
    const key = broker.toLocaleLowerCase("nb-NO");
    const group = grouped.get(key) ?? { broker, estimates: [] };
    group.estimates.push(estimate);
    grouped.set(key, group);
  }
  const columns = new Map<string, QuarterColumn>();
  const brokers: QuarterBrokerRow[] = [];
  for (const group of [...grouped.values()].sort((a, b) => a.broker.localeCompare(b.broker, "nb-NO"))) {
    const publishedDate = group.estimates.map((item) => item.published_date || "").sort().at(-1) || null;
    // A newer publication replaces its broker's entire set. Do not backfill
    // absent metrics from that broker's older note.
    const current = group.estimates.filter((item) => !publishedDate || item.published_date === publishedDate);
    const selected = new Map<string, NextQuarterEstimate>();
    for (const estimate of current) {
      const hasAmount = Number.isFinite(estimate.value_mbrl);
      const hasPercent = Number.isFinite(estimate.value_pct);
      if (!estimate.metric || hasAmount === hasPercent) continue;
      const unit = hasAmount ? "mbrl" : "pct";
      const key = `${estimate.metric}:${unit}`;
      const previous = selected.get(key);
      if (previous?.source_evidence === "PDF_TABLE_VERIFIED" && estimate.source_evidence !== "PDF_TABLE_VERIFIED") continue;
      selected.set(key, estimate);
      if (!columns.has(key)) columns.set(key, { key, metric: estimate.metric, label: estimate.label, unit });
    }
    const verifiedDate = current.map((item) => item.verified_date || "").sort().at(-1) || null;
    const sourceEvidence = current.map((item) => item.source_evidence || "").find(Boolean) || null;
    const row: QuarterBrokerRow = { broker: group.broker, publishedDate, verifiedDate, sourceEvidence, sourceUrls: [], values: {} };
    for (const [key, estimate] of selected) {
      row.values[key] = { value: Number.isFinite(estimate.value_mbrl) ? estimate.value_mbrl! : estimate.value_pct!, derived: false };
      if (estimate.source_url && !row.sourceUrls.includes(estimate.source_url)) row.sourceUrls.push(estimate.source_url);
    }
    // Web articles may disclose only revenue and a margin. Derive EBITDA from
    // these figures in the same broker's source, explicitly flagging the estimate
    // as calculated rather than published as an EBITDA amount.
    const revenue = row.values["revenue_mbrl:mbrl"]?.value;
    const ebitdaKey = "adjusted_ebitda_mbrl:mbrl";
    const publishedMargin = row.values["ebitda_margin_pct:pct"]?.value;
    if (!row.values[ebitdaKey] && revenue != null && publishedMargin != null) {
      const derivedEbitda = revenue * publishedMargin / 100;
      if (Number.isFinite(derivedEbitda)) {
        row.values[ebitdaKey] = {
          value: derivedEbitda,
          derived: true,
          derivation: "Beregnet fra meglerhusets omsetning og EBITDA-margin; EBITDA-beløpet er ikke eksplisitt oppgitt",
        };
        if (!columns.has(ebitdaKey)) {
          columns.set(ebitdaKey, { key: ebitdaKey, metric: "adjusted_ebitda_mbrl", label: "Justert EBITDA", unit: "mbrl" });
        }
      }
    }
    // Some broker previews omit margin. Derive it within this broker/publication,
    // using the same adjusted EBITDA definition as the explicit margin.
    const ebitda = row.values["adjusted_ebitda_mbrl:mbrl"]?.value;
    const marginKey = "ebitda_margin_pct:pct";
    if (!row.values[marginKey] && revenue != null && revenue !== 0 && ebitda != null) {
      const margin = ebitda / revenue * 100;
      if (Number.isFinite(margin)) {
        row.values[marginKey] = { value: margin, derived: true, derivation: "Beregnet fra meglerhusets oppgitte omsetning og justerte EBITDA" };
        if (!columns.has(marginKey)) columns.set(marginKey, { key: marginKey, metric: "ebitda_margin_pct", label: "Justert EBITDA-margin", unit: "pct" });
      }
    }
    if (Object.keys(row.values).length > 0) brokers.push(row);
  }
  const orderedColumns = [...columns.values()].sort((a, b) => {
    const priority = (metric: string) => {
      const index = MAIN_QUARTER_METRICS.indexOf(metric);
      return index < 0 ? MAIN_QUARTER_METRICS.length : index;
    };
    return priority(a.metric) - priority(b.metric);
  });
  const averages: Record<string, { value: number | null; count: number }> = {};
  for (const column of orderedColumns) {
    const values = brokers.flatMap((row) => row.values[column.key] ? [row.values[column.key].value] : []);
    averages[column.key] = {
      value: values.length ? values.reduce((sum, value) => sum + value / values.length, 0) : null,
      count: values.length,
    };
  }
  return { columns: orderedColumns, brokers, averages };
}

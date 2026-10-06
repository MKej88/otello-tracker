export type BemobiAfterOslo = {
  ready: boolean;
  status: string;
  oslo_close_at?: string;
  generated_at?: string;
  change_pct?: number;
  change_brl?: number;
  reference?: { price: number; observed_at: string; source: string; approximate: boolean };
  latest?: { price: number; observed_at: string; source: string; delay_minutes?: number | null };
  points?: Array<{ at: string; change_pct: number }>;
};

export function displayedChange(data: BemobiAfterOslo | null, refreshFailed = false) {
  return !refreshFailed && data?.ready && data.status === "ready"
    && Number.isFinite(data.change_pct) ? data.change_pct! : null;
}

export function statusLabel(status?: string, refreshFailed = false): string {
  if (refreshFailed) return "Kunne ikke oppdatere kursdata";
  switch (status) {
    case "waiting_reference": return "Venter på forsinket kurs ved Oslo-slutt";
    case "missing_reference": return "Mangler kurs ved Oslo-slutt";
    case "waiting_quote": return "Venter på neste Bemobi-kurs";
    case "stale_quote": return "Siste Bemobi-kurs er for gammel";
    case "ready": return "Endring i BRL";
    default: return "Laster kursgrunnlag …";
  }
}

export function movementChart(points: BemobiAfterOslo["points"]) {
  const valid = (points ?? []).filter(point =>
    Number.isFinite(Date.parse(point.at)) && Number.isFinite(point.change_pct),
  ).sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
  if (valid.length < 2) return null;
  const start = Date.parse(valid[0].at);
  const end = Date.parse(valid[valid.length - 1].at);
  if (end <= start) return null;
  const low = Math.min(0, ...valid.map(point => point.change_pct));
  const high = Math.max(0, ...valid.map(point => point.change_pct));
  const span = high - low || 1;
  const min = low - span * .15;
  const max = high + span * .15;
  const y = (value: number) => 92 - ((value - min) / (max - min)) * 84;
  return {
    line: valid.map(point => `${8 + ((Date.parse(point.at) - start) / (end - start)) * 464},${y(point.change_pct)}`).join(" "),
    zeroY: y(0),
    start: valid[0].at,
    end: valid[valid.length - 1].at,
  };
}

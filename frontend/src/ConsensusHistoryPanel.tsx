export type ConsensusHistoryLink = {
  events?: Array<{
    period: string;
    result_date: string;
    result_source?: string | null;
    result_source_url?: string | null;
    expectation?: {
      broker?: string | null;
      published_date?: string | null;
      source_url?: string | null;
      metrics?: Array<{
        metric: string;
        label: string;
        estimate: number;
        actual: number;
        beat_miss_pct?: number | null;
      }>;
    };
    model_revision?: {
      status?: string | null;
      broker?: string | null;
      before_date?: string | null;
      after_date?: string | null;
      target_before_brl?: number | null;
      target_after_brl?: number | null;
      target_revision_pct?: number | null;
      days_after_result?: number | null;
      source_url?: string | null;
      checked_date?: string | null;
      note?: string | null;
      estimate_revisions?: Array<{
        label: string;
        unit?: string | null;
        before?: number | null;
        after?: number | null;
        change_pp?: number | null;
        before_source_url?: string | null;
        after_source_url?: string | null;
        note?: string | null;
      }>;
    };
    market_reaction?: {
      status?: string | null;
      result_date?: string | null;
      pre?: { date: string; price_brl: number; source?: string | null } | null;
      day1?: { date: string; price_brl: number; source?: string | null } | null;
      day5?: { date: string; price_brl: number; source?: string | null } | null;
      reaction_1d_pct?: number | null;
      reaction_5d_pct?: number | null;
      method?: string | null;
    };
  }>;
  forward_revision_tracker?: {
    source?: string | null;
    baseline_date?: string | null;
    latest_date?: string | null;
    comparison_ready?: boolean;
    same_source_snapshots?: number | null;
    latest_changes?: Array<{
      year: number;
      metric: string;
      label: string;
      before: number;
      after: number;
      change?: number | null;
      change_pct?: number | null;
    }>;
    note?: string | null;
  };
  method_note?: string | null;
};

export default function ConsensusHistoryPanel(_: { history?: ConsensusHistoryLink | null }) {
  return null;
}

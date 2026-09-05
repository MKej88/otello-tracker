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

function finite(value?: number | null): value is number {
  return value != null && Number.isFinite(value);
}

function number(value?: number | null, digits = 1) {
  if (!finite(value)) return "–";
  return value.toLocaleString("nb-NO", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function signedPct(value?: number | null, digits = 1) {
  if (!finite(value)) return "–";
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}${number(Math.abs(value), digits)} %`;
}

function dateLabel(input?: string | null) {
  if (!input) return "–";
  const [year, month, day] = input.split("-");
  return year && month && day ? `${day}.${month}.${year}` : input;
}

function tone(value?: number | null) {
  if (!finite(value) || value === 0) return "neutral";
  return value > 0 ? "positive" : "negative";
}

function revisionValue(input?: number | null, unit?: string | null) {
  if (!finite(input)) return "–";
  if (unit?.includes("%")) return `${number(input, 1)} %`;
  return number(input, 1);
}

export default function ConsensusHistoryPanel({ history }: { history?: ConsensusHistoryLink | null }) {
  const events = [...(history?.events ?? [])].reverse();
  const tracker = history?.forward_revision_tracker;
  const visibleEvents = events.filter((event) => {
    const revision = event.model_revision;
    const reaction = event.market_reaction;
    return revision?.status === "PUBLIC_UPDATE"
      || revision?.status === "WAITING_FOR_PUBLIC_POST_REPORT_MODEL"
      || reaction?.status === "OK";
  }).slice(0, 3);
  const latestChanges = tracker?.comparison_ready ? tracker.latest_changes ?? [] : [];

  if (visibleEvents.length === 0 && latestChanges.length === 0) return null;

  return (
    <section className="card consensusRevisionSection">
      <div className="cardHeader">
        <div>
          <span className="label">ETTER RESULTAT</span>
          <h2>Estimat- og kursmålrevisjoner</h2>
        </div>
        <small>Forventning → faktisk → revisjon → kursreaksjon</small>
      </div>

      {latestChanges.length > 0 && (
        <div className="consensusForwardRevision">
          <div className="consensusForwardRevisionHeader">
            <div>
              <span>Siste meglermodell-revisjon</span>
              <strong>{tracker?.source ?? "Meglerhus"}</strong>
            </div>
            <small>{dateLabel(tracker?.baseline_date)} → {dateLabel(tracker?.latest_date)}</small>
          </div>
          <div className="consensusForwardRevisionGrid">
            {latestChanges.slice(0, 6).map((change) => (
              <div key={`${change.year}-${change.metric}`}>
                <span>{change.label} {change.year}E</span>
                <strong>{number(change.before, 1)} → {number(change.after, 1)}</strong>
                <small className={tone(change.change_pct)}>{signedPct(change.change_pct)}</small>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="consensusRevisionEvents">
        {visibleEvents.map((event) => {
          const revision = event.model_revision;
          const reaction = event.market_reaction;
          const hasTargetRevision = finite(revision?.target_before_brl) && finite(revision?.target_after_brl);
          const waitingForModel = revision?.status === "WAITING_FOR_PUBLIC_POST_REPORT_MODEL";
          const estimateRevisions = revision?.estimate_revisions ?? [];
          return (
            <article key={event.period} className="consensusRevisionEvent">
              <div className="consensusRevisionEventHeader">
                <div><strong>{event.period}</strong><span>{dateLabel(event.result_date)}</span></div>
                {revision?.broker && <span>{revision.broker}</span>}
              </div>

              <div className="consensusRevisionEventGrid">
                <div>
                  <span>Kursmål</span>
                  {hasTargetRevision ? (
                    <>
                      <strong>R$ {number(revision?.target_before_brl, 2)} → R$ {number(revision?.target_after_brl, 2)}</strong>
                      <small className={tone(revision?.target_revision_pct)}>{signedPct(revision?.target_revision_pct)}</small>
                    </>
                  ) : waitingForModel ? (
                    <><strong>Venter på offentlig modell</strong><small>Kursmål etter resultat er ikke publisert/verifisert.</small></>
                  ) : <strong>–</strong>}
                </div>

                <div>
                  <span>BMOB3 reaksjon</span>
                  {reaction?.status === "OK" ? (
                    <>
                      <strong className={tone(reaction.reaction_1d_pct)}>1d {signedPct(reaction.reaction_1d_pct)}</strong>
                      <small className={tone(reaction.reaction_5d_pct)}>5d {signedPct(reaction.reaction_5d_pct)}</small>
                    </>
                  ) : <strong>–</strong>}
                </div>
              </div>

              {estimateRevisions.length > 0 && (
                <div className="consensusEstimateRevisionRows">
                  {estimateRevisions.slice(0, 4).map((item) => (
                    <div key={`${event.period}-${item.label}`}>
                      <span>{item.label}</span>
                      <strong>{revisionValue(item.before, item.unit)} → {revisionValue(item.after, item.unit)}</strong>
                      {finite(item.change_pp) && <small className={tone(item.change_pp)}>{item.change_pp > 0 ? "+" : ""}{number(item.change_pp, 1)} pp</small>}
                    </div>
                  ))}
                </div>
              )}
            </article>
          );
        })}
      </div>

      {history?.method_note && <p className="consensusNote">{history.method_note}</p>}
    </section>
  );
}

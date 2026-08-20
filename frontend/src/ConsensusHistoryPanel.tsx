import "./consensus-history.css";

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
    comparison_ready?: boolean;
    same_source_snapshots?: number | null;
    note?: string | null;
  };
  method_note?: string | null;
};

function value(input: number | null | undefined, digits = 1) {
  if (input == null || !Number.isFinite(input)) return "–";
  return input.toLocaleString("nb-NO", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits
  });
}

function signedPct(input: number | null | undefined, digits = 1) {
  if (input == null || !Number.isFinite(input)) return "–";
  return `${input > 0 ? "+" : ""}${value(input, digits)} %`;
}

function dateLabel(input?: string | null) {
  if (!input) return "–";
  const [year, month, day] = input.split("-");
  return year && month && day ? `${day}.${month}.${year}` : input;
}

function SourceLink({ url, children }: { url?: string | null; children: React.ReactNode }) {
  if (!url) return <>{children}</>;
  return <a href={url} target="_blank" rel="noreferrer">{children}</a>;
}

export default function ConsensusHistoryPanel({ history }: { history?: ConsensusHistoryLink | null }) {
  if (!history) return null;
  const events = history.events ?? [];
  const tracker = history.forward_revision_tracker;

  return (
    <section className="card consensusHistoryCard">
      <div className="cardHeader">
        <div>
          <span className="label">Rapporthistorikk</span>
          <h2>Forventning → faktisk → revisjon → kursreaksjon</h2>
        </div>
      </div>

      <div className="consensusEventGrid">
        {events.map((event) => {
          const revision = event.model_revision;
          const reaction = event.market_reaction;
          const waitingRevision = revision?.status === "WAITING_FOR_PUBLIC_POST_REPORT_MODEL";
          return (
            <article className="consensusEvent" key={event.period}>
              <div className="consensusEventHeader">
                <div>
                  <strong>{event.period}</strong>
                  <span>Rapportert {dateLabel(event.result_date)}</span>
                </div>
                <SourceLink url={event.result_source_url}><span>Kilderapport →</span></SourceLink>
              </div>

              <div className="consensusEventSteps">
                <div className="consensusEventStep">
                  <span className="stepNumber">1</span>
                  <div>
                    <small>FORVENTNING</small>
                    <strong>{event.expectation?.broker ?? "–"}</strong>
                    {(event.expectation?.metrics ?? []).map((metric) => (
                      <p key={`${event.period}-${metric.metric}-estimate`}>
                        {metric.label}: <b>R$ {value(metric.estimate, 1)}m</b>
                      </p>
                    ))}
                    <SourceLink url={event.expectation?.source_url}><em>Preview {dateLabel(event.expectation?.published_date)} →</em></SourceLink>
                  </div>
                </div>

                <div className="consensusEventStep">
                  <span className="stepNumber">2</span>
                  <div>
                    <small>FAKTISK</small>
                    <strong>{event.period}</strong>
                    {(event.expectation?.metrics ?? []).map((metric) => (
                      <p key={`${event.period}-${metric.metric}-actual`}>
                        {metric.label}: <b>R$ {value(metric.actual, 1)}m</b>{" "}
                        <span className={(metric.beat_miss_pct ?? 0) >= 0 ? "positive" : "negative"}>
                          {signedPct(metric.beat_miss_pct)}
                        </span>
                      </p>
                    ))}
                  </div>
                </div>

                <div className="consensusEventStep">
                  <span className="stepNumber">3</span>
                  <div>
                    <small>ESTIMATREVISJON</small>
                    {waitingRevision ? (
                      <>
                        <strong>Venter på offentlig modell</strong>
                        <p>Siste verifiserte XP-kursmål før rapport: <b>R$ {value(revision?.target_before_brl, 2)}</b></p>
                      </>
                    ) : (
                      <>
                        <strong>
                          R$ {value(revision?.target_before_brl, 2)} → R$ {value(revision?.target_after_brl, 2)}
                        </strong>
                        <p>
                          Kursmål: <span className={(revision?.target_revision_pct ?? 0) >= 0 ? "positive" : "negative"}>
                            {signedPct(revision?.target_revision_pct)}
                          </span>
                          {revision?.days_after_result != null ? ` · ${revision.days_after_result} dager etter rapport` : ""}
                        </p>
                      </>
                    )}
                    {(revision?.estimate_revisions ?? []).map((item) => (
                      <p key={`${event.period}-${item.label}`}>
                        {item.label}: <b>{value(item.before, 0)} % → {value(item.after, 0)} %</b>{" "}
                        <span className={(item.change_pp ?? 0) >= 0 ? "positive" : "negative"}>
                          {item.change_pp != null ? `${item.change_pp > 0 ? "+" : ""}${value(item.change_pp, 0)} pp` : ""}
                        </span>
                      </p>
                    ))}
                    <SourceLink url={revision?.source_url}><em>Modellkilde →</em></SourceLink>
                  </div>
                </div>

                <div className="consensusEventStep">
                  <span className="stepNumber">4</span>
                  <div>
                    <small>KURSREAKSJON</small>
                    {reaction?.status === "OK" ? (
                      <>
                        <strong className={(reaction.reaction_1d_pct ?? 0) >= 0 ? "positive" : "negative"}>
                          {signedPct(reaction.reaction_1d_pct)} første handelsdag
                        </strong>
                        <p>
                          R$ {value(reaction.pre?.price_brl, 2)} → R$ {value(reaction.day1?.price_brl, 2)}
                        </p>
                        <p>
                          5 handelsdager: <b className={(reaction.reaction_5d_pct ?? 0) >= 0 ? "positive" : "negative"}>
                            {signedPct(reaction.reaction_5d_pct)}
                          </b>
                        </p>
                      </>
                    ) : (
                      <><strong>Mangler kurshistorikk</strong><p>Reaksjonen fylles inn når BMOB3-data finnes for perioden.</p></>
                    )}
                  </div>
                </div>
              </div>

              {(revision?.note || (revision?.estimate_revisions ?? []).some((item) => item.note)) && (
                <div className="consensusEventNote">
                  {revision?.note}
                  {(revision?.estimate_revisions ?? []).map((item) => item.note ? <span key={`${event.period}-${item.label}-note`}>{item.note}</span> : null)}
                </div>
              )}
            </article>
          );
        })}
      </div>

      <div className="consensusRevisionBaseline">
        <div>
          <span className="label">Løpende konsensusrevisjoner</span>
          <strong>{tracker?.comparison_ready ? "Sammenligning aktiv" : "Baseline startet"}</strong>
        </div>
        <div>
          <span>Kilde</span><b>{tracker?.source ?? "–"}</b>
        </div>
        <div>
          <span>Første snapshot</span><b>{dateLabel(tracker?.baseline_date)}</b>
        </div>
        <div>
          <span>Samme-kilde snapshots</span><b>{tracker?.same_source_snapshots ?? 0}</b>
        </div>
      </div>
      {tracker?.note && <p className="consensusNote">{tracker.note}</p>}
      {history.method_note && <p className="consensusNote">{history.method_note}</p>}
    </section>
  );
}

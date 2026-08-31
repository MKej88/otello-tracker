import { useEffect, useState } from "react";
import ResourceNotice from "./ResourceNotice";
import ConsensusHistoryPanel, { type ConsensusHistoryLink } from "./ConsensusHistoryPanel";
import "./consensus-page.css";

type Analyst = {
  institution: string;
  analyst: string;
  rating: "BUY" | "HOLD" | "SELL" | string;
  target_price_brl: number;
  last_update: string;
};

type BrokerYear = {
  year: number;
  revenue_mbrl?: number | null;
  ebitda_mbrl?: number | null;
  ebit_mbrl?: number | null;
  net_income_mbrl?: number | null;
  eps_brl?: number | null;
  net_debt_mbrl?: number | null;
  market_cap_mbrl?: number | null;
  enterprise_value_mbrl?: number | null;
  pe?: number | null;
  earnings_yield_pct?: number | null;
  ev_ebitda?: number | null;
  ev_ebit?: number | null;
};

type NextQuarterEstimate = {
  metric: string;
  label: string;
  value_mbrl: number;
  broker?: string | null;
  source_url?: string | null;
  published_date?: string | null;
};

type BeatMissMetric = {
  metric: string;
  label: string;
  estimate: number;
  actual: number;
  beat_miss_pct?: number | null;
};

type BeatMissPeriod = {
  period: string;
  broker: string;
  published_date: string;
  source_url: string;
  metrics: BeatMissMetric[];
};

type ConsensusPayload = {
  ready: boolean;
  reason?: string;
  as_of_date?: string | null;
  market?: {
    price_brl?: number | null;
    price_date?: string | null;
    price_source?: string | null;
  };
  coverage?: {
    analyst_count?: number | null;
    buy_count?: number | null;
    hold_count?: number | null;
    sell_count?: number | null;
    buy_pct?: number | null;
    average_target_brl?: number | null;
    high_target_brl?: number | null;
    low_target_brl?: number | null;
    upside_to_average_pct?: number | null;
    source?: string | null;
    source_url?: string | null;
    checked_date?: string | null;
  };
  analysts?: Analyst[];
  broker_estimates?: {
    source?: string | null;
    source_url?: string | null;
    published_date?: string | null;
    quality?: string | null;
    broker_count?: number | null;
    year_range?: string | null;
    years?: BrokerYear[];
    note?: string | null;
  };
  next_quarter?: {
    period?: string | null;
    status?: string | null;
    estimates?: NextQuarterEstimate[];
    tracked_metrics?: string[];
    note?: string | null;
  };
  beat_miss?: BeatMissPeriod[];
  history_link?: ConsensusHistoryLink;
  reference_model?: {
    broker?: string | null;
    rating?: string | null;
    target_price_brl?: number | null;
    published_date?: string | null;
    pe_2026_reported?: number | null;
    ev_ebitda_2026_reported?: number | null;
    source_url?: string | null;
    note?: string | null;
  };
  sources?: Array<{ label: string; source: string; url?: string | null }>;
};

const AUTO_REFRESH_MS = 5 * 60 * 1000;

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

function ratingLabel(input?: string | null) {
  if (input === "BUY") return "Kjøp";
  if (input === "HOLD") return "Hold";
  if (input === "SELL") return "Selg";
  return input ?? "–";
}

function SourceLink({ url, children }: { url?: string | null; children: React.ReactNode }) {
  if (!url) return <span>{children}</span>;
  return <a href={url} target="_blank" rel="noreferrer">{children}</a>;
}

export default function ConsensusPage() {
  const [data, setData] = useState<ConsensusPayload | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    const load = () => {
      fetch("/api/bemobi/consensus")
        .then((response) => {
          if (!response.ok) throw new Error("Konsensus API-feil");
          return response.json() as Promise<ConsensusPayload>;
        })
        .then((result) => {
          if (!active) return;
          setData(result);
          setFailed(false);
        })
        .catch(() => {
          if (!active) return;
          setFailed(true);
        });
    };

    load();
    const timer = window.setInterval(load, AUTO_REFRESH_MS);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  if (data == null && !failed) return <ResourceNotice>Laster konsensus …</ResourceNotice>;
  if (failed && data == null) return <ResourceNotice kind="error">Kunne ikke hente konsensusdata.</ResourceNotice>;
  if (!data?.ready) return <div className="consensusNotice"><strong>Konsensus er ikke klar.</strong><span>{data?.reason}</span></div>;

  const coverage = data.coverage;
  const market = data.market;
  const broker = data.broker_estimates;
  const brokerYears = broker?.years ?? [];
  const brokerRange = broker?.year_range ?? (
    brokerYears.length === 0
      ? "Forward"
      : brokerYears.length === 1
        ? `${brokerYears[0].year}E`
        : `${brokerYears[0].year}E–${brokerYears[brokerYears.length - 1].year}E`
  );
  const nextQuarter = data.next_quarter;
  const nextQuarterEstimates = nextQuarter?.estimates ?? [];
  const hasPublicPreview = nextQuarter?.status === "PUBLIC_ESTIMATES_AVAILABLE" && nextQuarterEstimates.length > 0;
  const previewSourceUrl = nextQuarterEstimates.find((estimate) => estimate.source_url)?.source_url;
  const previewPublishedDate = nextQuarterEstimates.find((estimate) => estimate.published_date)?.published_date;
  const analysts = data.analysts ?? [];
  const beatMiss = data.beat_miss ?? [];

  return (
    <div className="consensusPage">
      <section className="card consensusHero">
        <div>
          <span className="label">BEMOBI / KONSENSUS</span>
          <h2>Forventninger mot dagens pris</h2>
          <p>
            Offentlig analytikerdekning, kursmål, kildeverifiserte meglerestimater og historisk beat/miss.
            Husspesifikke estimater vises bare når vi kan knytte dem til en offentlig meglerkilde.
          </p>
        </div>
        <div className="consensusHeroPrice">
          <span>BMOB3</span>
          <strong>R$ {value(market?.price_brl, 2)}</strong>
          <small>{dateLabel(market?.price_date)}</small>
        </div>
      </section>

      <section className="consensusKpis">
        <article className="card">
          <span className="label">Konsensus kursmål</span>
          <strong>R$ {value(coverage?.average_target_brl, 2)}</strong>
          <small className={(coverage?.upside_to_average_pct ?? 0) >= 0 ? "positive" : "negative"}>
            {signedPct(coverage?.upside_to_average_pct)} mot dagens kurs
          </small>
        </article>
        <article className="card">
          <span className="label">Spenn</span>
          <strong>R$ {value(coverage?.low_target_brl, 2)}–{value(coverage?.high_target_brl, 2)}</strong>
          <small>{coverage?.analyst_count ?? "–"} analytikere</small>
        </article>
        <article className="card">
          <span className="label">Kjøpsandel</span>
          <strong>{value(coverage?.buy_pct, 0)} %</strong>
          <small>{coverage?.buy_count ?? 0} kjøp · {coverage?.hold_count ?? 0} hold · {coverage?.sell_count ?? 0} selg</small>
        </article>
        <article className="card">
          <span className="label">Neste kvartal</span>
          <strong>{nextQuarter?.period ?? "–"}</strong>
          <small>{hasPublicPreview ? `${nextQuarterEstimates.length} verifiserte XP-estimater` : "Venter på verifiserte estimater"}</small>
        </article>
      </section>

      <section className="card consensusCoverage">
        <div className="cardHeader">
          <div><span className="label">Analytikerdekning</span><h2>Meglerhus og kursmål</h2></div>
          <SourceLink url={coverage?.source_url}><span className="pill">Bemobi IR</span></SourceLink>
        </div>
        <div className="consensusTableWrap">
          <table className="consensusTable">
            <thead><tr><th>Meglerhus</th><th>Analytiker</th><th>Anbefaling</th><th>Kursmål</th><th>Oppdatert</th></tr></thead>
            <tbody>
              {analysts.map((analyst) => (
                <tr key={analyst.institution}>
                  <td><strong>{analyst.institution}</strong></td>
                  <td>{analyst.analyst}</td>
                  <td><span className={`rating ${analyst.rating.toLowerCase()}`}>{ratingLabel(analyst.rating)}</span></td>
                  <td>R$ {value(analyst.target_price_brl, 2)}</td>
                  <td>{dateLabel(analyst.last_update)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="card consensusForward">
        <div className="cardHeader">
          <div>
            <span className="label">Meglerestimater</span>
            <h2>{brokerRange}</h2>
          </div>
          <SourceLink url={broker?.source_url}><span className="pill">{broker?.source ?? "Meglerkilde"}</span></SourceLink>
        </div>
        <p className="consensusNote">
          Kildeverifisert modell fra ett meglerhus. Dette er ikke et anonymt aggregat; når flere offentlige modeller er tilgjengelige,
          beregner trackeren konsensus på tvers av husene.
        </p>
        <div className="consensusTableWrap">
          <table className="consensusTable forwardTable">
            <thead>
              <tr>
                <th>År</th><th>Omsetning</th><th>EBITDA</th><th>Resultat</th><th>EPS</th><th>Netto gjeld / (cash)</th>
                <th>P/E</th><th>EV/EBITDA</th><th>Earnings yield</th>
              </tr>
            </thead>
            <tbody>
              {brokerYears.map((year) => (
                <tr key={year.year}>
                  <td><strong>{year.year}E</strong></td>
                  <td>R$ {value(year.revenue_mbrl, 0)}m</td>
                  <td>R$ {value(year.ebitda_mbrl, 1)}m</td>
                  <td>R$ {value(year.net_income_mbrl, 1)}m</td>
                  <td>R$ {value(year.eps_brl, 2)}</td>
                  <td>R$ {value(year.net_debt_mbrl, 0)}m</td>
                  <td>{value(year.pe, 1)}x</td>
                  <td>{value(year.ev_ebitda, 1)}x</td>
                  <td>{value(year.earnings_yield_pct, 1)} %</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="consensusNote">{broker?.note}</p>
      </section>

      <section className="consensusTwoColumn">
        <article className="card nextQuarterCard">
          <div className="cardHeader">
            <div><span className="label">Neste rapport</span><h2>{nextQuarter?.period}</h2></div>
            <span className={`pill${hasPublicPreview ? "" : " muted"}`}>{hasPublicPreview ? "XP-PREVIEW" : "VENTER"}</span>
          </div>
          <p>{nextQuarter?.note}</p>
          {hasPublicPreview ? (
            <>
              <div className="referenceGrid">
                {nextQuarterEstimates.map((estimate) => (
                  <div key={estimate.metric}>
                    <span>{estimate.label}</span>
                    <strong>R$ {value(estimate.value_mbrl, 1)}m</strong>
                  </div>
                ))}
              </div>
              <SourceLink url={previewSourceUrl}>
                <span className="consensusSourceAction">
                  Offentlig XP-preview{previewPublishedDate ? ` · ${dateLabel(previewPublishedDate)}` : ""} →
                </span>
              </SourceLink>
              <small>Meglerhus-spesifikt forhåndsestimat, ikke markedskonsensus.</small>
            </>
          ) : (
            <>
              <div className="trackedMetrics">
                {(nextQuarter?.tracked_metrics ?? []).map((metric) => <span key={metric}>{metric}</span>)}
              </div>
              <small>Estimatene fylles inn når de kan verifiseres fra en offentlig meglerkilde.</small>
            </>
          )}
        </article>

        <article className="card xpReference">
          <div className="cardHeader">
            <div><span className="label">Referansemodell</span><h2>{data.reference_model?.broker ?? "XP"}</h2></div>
            <span className="pill">{ratingLabel(data.reference_model?.rating).toUpperCase()}</span>
          </div>
          <div className="referenceGrid">
            <div><span>Kursmål</span><strong>R$ {value(data.reference_model?.target_price_brl, 2)}</strong></div>
            <div><span>P/E 2026 ved rapportdato</span><strong>{value(data.reference_model?.pe_2026_reported, 1)}x</strong></div>
            <div><span>EV/EBITDA 2026 ved rapportdato</span><strong>{value(data.reference_model?.ev_ebitda_2026_reported, 1)}x</strong></div>
          </div>
          <SourceLink url={data.reference_model?.source_url}><span className="consensusSourceAction">Åpne XP-modelloppdatering →</span></SourceLink>
          <p className="consensusNote">{data.reference_model?.note}</p>
        </article>
      </section>

      <section className="card beatMissCard">
        <div className="cardHeader"><div><span className="label">Historikk</span><h2>Beat / miss mot offentlig XP-preview</h2></div></div>
        <div className="beatMissGrid">
          {beatMiss.map((period) => (
            <article key={period.period}>
              <div className="beatMissHeader">
                <div><strong>{period.period}</strong><span>{period.broker}</span></div>
                <SourceLink url={period.source_url}><span>Kilde →</span></SourceLink>
              </div>
              {period.metrics.map((metric) => (
                <div className="beatMissRow" key={`${period.period}-${metric.metric}`}>
                  <span>{metric.label}</span>
                  <div><small>Est. R$ {value(metric.estimate, 1)}m</small><small>Faktisk R$ {value(metric.actual, 1)}m</small></div>
                  <strong className={(metric.beat_miss_pct ?? 0) >= 0 ? "positive" : "negative"}>{signedPct(metric.beat_miss_pct)}</strong>
                </div>
              ))}
            </article>
          ))}
        </div>
        <p className="consensusNote">Dette er meglerhus-spesifikk beat/miss, ikke markedskonsensus, inntil vi har flere verifiserte kvartalsestimater per periode.</p>
      </section>

      <ConsensusHistoryPanel history={data.history_link} />

      <section className="card consensusSources">
        <div className="cardHeader"><div><span className="label">Kilder</span><h2>Datagrunnlag</h2></div></div>
        <div className="sourceList">
          {(data.sources ?? []).map((source) => (
            <div key={source.label}><span>{source.label}</span><strong><SourceLink url={source.url}>{source.source}</SourceLink></strong></div>
          ))}
        </div>
      </section>
    </div>
  );
}

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { fetchPreloadedJson } from "./navigationDataPreload";
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
  sources?: Array<{ label: string; source: string; url?: string | null }>;
};

type BeatSummary = {
  key: string;
  label: string;
  beats: number;
  total: number;
  averagePct: number | null;
};

const AUTO_REFRESH_MS = 5 * 60 * 1000;

function finite(input: number | null | undefined): input is number {
  return input != null && Number.isFinite(input);
}

function value(input: number | null | undefined, digits = 1) {
  if (!finite(input)) return "–";
  return input.toLocaleString("nb-NO", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function signedPct(input: number | null | undefined, digits = 1) {
  if (!finite(input)) return "–";
  const prefix = input > 0 ? "+" : input < 0 ? "−" : "";
  return `${prefix}${value(Math.abs(input), digits)} %`;
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

function tone(input: number | null | undefined) {
  if (!finite(input) || input === 0) return "neutral";
  return input > 0 ? "positive" : "negative";
}

function SourceLink({ url, children }: { url?: string | null; children: ReactNode }) {
  if (!url) return <span>{children}</span>;
  return <a href={url} target="_blank" rel="noreferrer">{children}</a>;
}

function pctChange(start: number | null | undefined, end: number | null | undefined) {
  if (!finite(start) || !finite(end) || start === 0) return null;
  return (end / start - 1) * 100;
}

function metricPriority(label: string) {
  const normalized = label.toLowerCase();
  if (normalized.includes("omset") || normalized.includes("revenue")) return 0;
  if (normalized.includes("ebitda")) return 1;
  if (normalized.includes("result") || normalized.includes("net income")) return 2;
  return 3;
}

function beatSummary(periods: BeatMissPeriod[]): BeatSummary[] {
  const grouped = new Map<string, { label: string; beats: number; total: number; sum: number; count: number }>();
  for (const period of periods) {
    for (const metric of period.metrics ?? []) {
      const key = metric.metric || metric.label;
      const current = grouped.get(key) ?? { label: metric.label, beats: 0, total: 0, sum: 0, count: 0 };
      current.total += 1;
      if (finite(metric.beat_miss_pct)) {
        if (metric.beat_miss_pct > 0) current.beats += 1;
        current.sum += metric.beat_miss_pct;
        current.count += 1;
      }
      grouped.set(key, current);
    }
  }
  return [...grouped.entries()]
    .map(([key, item]) => ({
      key,
      label: item.label,
      beats: item.beats,
      total: item.total,
      averagePct: item.count > 0 ? item.sum / item.count : null,
    }))
    .sort((left, right) => metricPriority(left.label) - metricPriority(right.label) || left.label.localeCompare(right.label))
    .slice(0, 4);
}

function findMetric(metrics: BeatMissMetric[], needle: string) {
  return metrics.find((metric) => metric.metric.toLowerCase().includes(needle) || metric.label.toLowerCase().includes(needle));
}

function findEstimate(estimates: NextQuarterEstimate[], needle: string) {
  return estimates.find((estimate) => estimate.metric.toLowerCase().includes(needle) || estimate.label.toLowerCase().includes(needle));
}

function actualForEstimate(estimate: NextQuarterEstimate, latest?: BeatMissPeriod) {
  if (!latest) return null;
  const exact = latest.metrics.find((metric) => metric.metric === estimate.metric);
  if (exact) return exact.actual;
  const label = estimate.label.toLowerCase();
  const loose = latest.metrics.find((metric) => {
    const candidate = metric.label.toLowerCase();
    return candidate === label || candidate.includes(label) || label.includes(candidate);
  });
  return loose?.actual ?? null;
}

function forwardMetricValue(metric: string, year: BrokerYear) {
  if (metric === "revenue") return finite(year.revenue_mbrl) ? `R$ ${value(year.revenue_mbrl, 0)}m` : "–";
  if (metric === "ebitda") return finite(year.ebitda_mbrl) ? `R$ ${value(year.ebitda_mbrl, 1)}m` : "–";
  if (metric === "margin") {
    return finite(year.ebitda_mbrl) && finite(year.revenue_mbrl) && year.revenue_mbrl !== 0
      ? `${value(year.ebitda_mbrl / year.revenue_mbrl * 100, 1)} %`
      : "–";
  }
  if (metric === "net_income") return finite(year.net_income_mbrl) ? `R$ ${value(year.net_income_mbrl, 1)}m` : "–";
  if (metric === "eps") return finite(year.eps_brl) ? `R$ ${value(year.eps_brl, 2)}` : "–";
  if (metric === "pe") return finite(year.pe) ? `${value(year.pe, 1)}x` : "–";
  if (metric === "ev_ebitda") return finite(year.ev_ebitda) ? `${value(year.ev_ebitda, 1)}x` : "–";
  return "–";
}

export default function ConsensusPage() {
  const [data, setData] = useState<ConsensusPayload | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    const load = (initial = false) => {
      const request = initial
        ? fetchPreloadedJson<ConsensusPayload>("/api/bemobi/consensus")
        : fetch("/api/bemobi/consensus").then((response) => {
            if (!response.ok) throw new Error("Konsensus API-feil");
            return response.json() as Promise<ConsensusPayload>;
          });
      request
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

    load(true);
    const timer = window.setInterval(load, AUTO_REFRESH_MS);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  const summary = useMemo(() => beatSummary(data?.beat_miss ?? []), [data?.beat_miss]);

  if (data == null && !failed) return <ResourceNotice>Laster konsensus …</ResourceNotice>;
  if (failed && data == null) return <ResourceNotice kind="error">Kunne ikke hente konsensusdata.</ResourceNotice>;
  if (!data?.ready) return <div className="consensusNotice"><strong>Konsensus er ikke klar.</strong><span>{data?.reason}</span></div>;

  const coverage = data.coverage;
  const market = data.market;
  const broker = data.broker_estimates;
  const brokerYears = broker?.years ?? [];
  const nextQuarter = data.next_quarter;
  const nextQuarterEstimates = nextQuarter?.estimates ?? [];
  const hasPublicPreview = nextQuarter?.status === "PUBLIC_ESTIMATES_AVAILABLE" && nextQuarterEstimates.length > 0;
  const previewSourceUrl = nextQuarterEstimates.find((estimate) => estimate.source_url)?.source_url;
  const previewPublishedDate = nextQuarterEstimates.find((estimate) => estimate.published_date)?.published_date;
  const previewBroker = nextQuarterEstimates.find((estimate) => estimate.broker)?.broker ?? "Meglerhus";
  const analysts = data.analysts ?? [];
  const beatMiss = data.beat_miss ?? [];
  const latestBeat = beatMiss.length > 0 ? beatMiss[beatMiss.length - 1] : undefined;
  const revenueEstimate = findEstimate(nextQuarterEstimates, "revenue") ?? findEstimate(nextQuarterEstimates, "omset");
  const ebitdaEstimate = findEstimate(nextQuarterEstimates, "ebitda");
  const latestRevenue = latestBeat ? (findMetric(latestBeat.metrics, "revenue") ?? findMetric(latestBeat.metrics, "omset")) : undefined;
  const latestEbitda = latestBeat ? findMetric(latestBeat.metrics, "ebitda") : undefined;
  const previewMargin = revenueEstimate && ebitdaEstimate && revenueEstimate.value_mbrl !== 0
    ? ebitdaEstimate.value_mbrl / revenueEstimate.value_mbrl * 100
    : null;
  const latestMargin = latestRevenue && latestEbitda && latestRevenue.actual !== 0
    ? latestEbitda.actual / latestRevenue.actual * 100
    : null;
  const targetLow = coverage?.low_target_brl;
  const targetHigh = coverage?.high_target_brl;
  const targetAverage = coverage?.average_target_brl;
  const marketPrice = market?.price_brl;
  const targetRangeReady = finite(targetLow) && finite(targetHigh) && targetHigh > targetLow;
  const rangePosition = (input?: number | null) => {
    if (!targetRangeReady || !finite(input)) return null;
    return Math.max(0, Math.min(100, (input - targetLow) / (targetHigh - targetLow) * 100));
  };

  const forwardRows = [
    ["revenue", "Omsetning"],
    ["ebitda", "EBITDA"],
    ["margin", "EBITDA-margin"],
    ["net_income", "Resultat"],
    ["eps", "EPS"],
    ["pe", "P/E"],
    ["ev_ebitda", "EV/EBITDA"],
  ] as const;

  return (
    <div className="consensusPage consensusPageV2">
      <section className="card consensusHero consensusHeroV2">
        <div>
          <span className="label">BEMOBI / KONSENSUS</span>
          <h2>Hva forventer markedet?</h2>
          <p>Kursmål, neste kvartals forventninger, historisk beat/miss og hvordan meglerestimater endres etter resultat.</p>
        </div>
        <div className="consensusHeroPrice">
          <span>BMOB3</span>
          <strong>R$ {value(marketPrice, 2)}</strong>
          <small>{dateLabel(market?.price_date)} · {market?.price_source ?? "marked"}</small>
        </div>
      </section>

      <section className="consensusKpis consensusKpisV2">
        <article className="card">
          <span className="label">Konsensusmål</span>
          <strong>R$ {value(targetAverage, 2)}</strong>
          <small className={tone(coverage?.upside_to_average_pct)}>{signedPct(coverage?.upside_to_average_pct)} mot dagens kurs</small>
        </article>
        <article className="card">
          <span className="label">Kjøpsandel</span>
          <strong>{value(coverage?.buy_pct, 0)} %</strong>
          <small>{coverage?.buy_count ?? 0} kjøp · {coverage?.hold_count ?? 0} hold · {coverage?.sell_count ?? 0} selg</small>
        </article>
        <article className="card">
          <span className="label">Neste rapport</span>
          <strong>{nextQuarter?.period ?? "–"}</strong>
          <small>{hasPublicPreview ? `${previewBroker}-preview tilgjengelig` : "Venter på offentlig preview"}</small>
        </article>
      </section>

      <section className="card consensusNextReport">
        <div className="cardHeader">
          <div><span className="label">NESTE RAPPORT</span><h2>{nextQuarter?.period ?? "Neste kvartal"} forventninger</h2></div>
          <span className={`pill${hasPublicPreview ? "" : " muted"}`}>{hasPublicPreview ? `${previewBroker.toUpperCase()}-PREVIEW` : "VENTER"}</span>
        </div>
        {hasPublicPreview ? (
          <>
            <div className="consensusTableWrap consensusNextTableWrap">
              <table className="consensusTable consensusNextTable">
                <thead>
                  <tr><th>Metric</th><th>Estimat</th><th>{latestBeat?.period ?? "Siste rapport"}</th><th>Vs. siste rapport</th><th>Beat-grense</th></tr>
                </thead>
                <tbody>
                  {nextQuarterEstimates.map((estimate) => {
                    const actual = actualForEstimate(estimate, latestBeat);
                    const change = pctChange(actual, estimate.value_mbrl);
                    return (
                      <tr key={estimate.metric}>
                        <td><strong>{estimate.label}</strong></td>
                        <td>R$ {value(estimate.value_mbrl, 1)}m</td>
                        <td>{finite(actual) ? `R$ ${value(actual, 1)}m` : "–"}</td>
                        <td className={tone(change)}>{signedPct(change)}</td>
                        <td>&gt; R$ {value(estimate.value_mbrl, 1)}m</td>
                      </tr>
                    );
                  })}
                  {finite(previewMargin) && (
                    <tr>
                      <td><strong>EBITDA-margin</strong></td>
                      <td>{value(previewMargin, 1)} %</td>
                      <td>{finite(latestMargin) ? `${value(latestMargin, 1)} %` : "–"}</td>
                      <td className={tone(pctChange(latestMargin, previewMargin))}>{signedPct(pctChange(latestMargin, previewMargin))}</td>
                      <td>&gt; {value(previewMargin, 1)} %</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            <div className="consensusPreviewMeta">
              <span>Beat = faktisk resultat over offentlig preview-estimat.</span>
              <SourceLink url={previewSourceUrl}>Kilde: {previewBroker}{previewPublishedDate ? ` · ${dateLabel(previewPublishedDate)}` : ""} →</SourceLink>
            </div>
            <p className="consensusNote">Meglerhus-spesifikt forhåndsestimat, ikke markedskonsensus.</p>
          </>
        ) : (
          <div className="consensusWaitingPreview">
            <strong>Ingen verifisert offentlig preview ennå.</strong>
            <p>{nextQuarter?.note ?? "Estimatene fylles inn når de kan verifiseres mot en offentlig meglerkilde."}</p>
            <div className="trackedMetrics">{(nextQuarter?.tracked_metrics ?? []).map((metric) => <span key={metric}>{metric}</span>)}</div>
          </div>
        )}
      </section>

      <section className="card consensusBeatSummary">
        <div className="cardHeader">
          <div><span className="label">HISTORISK TREFF</span><h2>Har estimatene vært konservative?</h2></div>
          <small>{beatMiss.length} rapportperioder med verifisert preview</small>
        </div>
        {summary.length > 0 ? (
          <div className="consensusBeatSummaryGrid">
            {summary.map((metric) => (
              <div key={metric.key}>
                <span>{metric.label}</span>
                <strong>{metric.beats}/{metric.total} beat</strong>
                <small className={tone(metric.averagePct)}>Snitt {signedPct(metric.averagePct)}</small>
              </div>
            ))}
          </div>
        ) : <div className="consensusEmptyInline">Ingen verifisert beat/miss-historikk ennå.</div>}
      </section>

      <section className="card consensusForward consensusForwardV2">
        <div className="cardHeader">
          <div><span className="label">FORWARD ESTIMATER</span><h2>{broker?.source ?? "Meglerestimat"}</h2></div>
          <SourceLink url={broker?.source_url}><span className="pill">{broker?.published_date ? dateLabel(broker.published_date) : "KILDE"}</span></SourceLink>
        </div>
        <p className="consensusNote">Kildeverifisert modell fra ett meglerhus. Dette er ikke et anonymt aggregat.</p>
        <div className="consensusTableWrap consensusForwardMatrixWrap">
          <table className="consensusTable consensusForwardMatrix">
            <thead><tr><th>Metric</th>{brokerYears.map((year) => <th key={year.year}>{year.year}E</th>)}</tr></thead>
            <tbody>
              {forwardRows.map(([metric, label]) => (
                <tr key={metric}>
                  <td><strong>{label}</strong></td>
                  {brokerYears.map((year) => <td key={`${metric}-${year.year}`}>{forwardMetricValue(metric, year)}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="consensusNetCashRow">
          {brokerYears.map((year) => (
            <span key={year.year}>{year.year}E: {finite(year.net_debt_mbrl) ? (year.net_debt_mbrl <= 0 ? `netto cash R$ ${value(Math.abs(year.net_debt_mbrl), 0)}m` : `netto gjeld R$ ${value(year.net_debt_mbrl, 0)}m`) : "netto gjeld/cash –"}</span>
          ))}
        </div>
        {broker?.note && <p className="consensusNote">{broker.note}</p>}
      </section>

      <ConsensusHistoryPanel history={data.history_link} />

      <section className="card consensusTargetRange">
        <div className="cardHeader">
          <div><span className="label">KURSMÅL</span><h2>Analytikernes spenn</h2></div>
          <SourceLink url={coverage?.source_url}><span className="pill">{coverage?.analyst_count ?? 0} ANALYTIKERE</span></SourceLink>
        </div>
        {targetRangeReady ? (
          <div className="targetRangeVisual">
            <div className="targetRangeNumbers"><span>Lav R$ {value(targetLow, 2)}</span><span>Snitt R$ {value(targetAverage, 2)}</span><span>Høy R$ {value(targetHigh, 2)}</span></div>
            <div className="targetRangeTrack">
              <i className="targetRangeAverage" style={{ left: `${rangePosition(targetAverage) ?? 50}%` }} />
              {rangePosition(marketPrice) != null && <i className="targetRangeMarket" style={{ left: `${rangePosition(marketPrice)}%` }} />}
            </div>
            <div className="targetRangeLegend"><span><i className="averageDot" />Konsensusmål</span><span><i className="marketDot" />BMOB3 R$ {value(marketPrice, 2)}</span></div>
          </div>
        ) : <div className="consensusEmptyInline">Kursmålsspenn mangler.</div>}
      </section>

      <section className="consensusDetailsStack">
        <details className="card consensusDisclosure">
          <summary><span><span className="label">DETALJER</span><strong>Analytikere og kursmål</strong></span><b>Vis</b></summary>
          <div className="consensusTableWrap">
            <table className="consensusTable analystTable">
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
        </details>

        <details className="card consensusDisclosure">
          <summary><span><span className="label">DETALJER</span><strong>Beat/miss per kvartal</strong></span><b>Vis</b></summary>
          <div className="beatMissGrid beatMissGridDetails">
            {beatMiss.map((period) => (
              <article key={period.period}>
                <div className="beatMissHeader"><div><strong>{period.period}</strong><span>{period.broker}</span></div><SourceLink url={period.source_url}><span>Kilde →</span></SourceLink></div>
                {period.metrics.map((metric) => (
                  <div className="beatMissRow" key={`${period.period}-${metric.metric}`}>
                    <span>{metric.label}</span>
                    <div><small>Est. R$ {value(metric.estimate, 1)}m</small><small>Faktisk R$ {value(metric.actual, 1)}m</small></div>
                    <strong className={tone(metric.beat_miss_pct)}>{signedPct(metric.beat_miss_pct)}</strong>
                  </div>
                ))}
              </article>
            ))}
          </div>
        </details>

        <details className="card consensusDisclosure">
          <summary><span><span className="label">DETALJER</span><strong>Kilder og metode</strong></span><b>Vis</b></summary>
          <div className="sourceList consensusSourceList">
            {(data.sources ?? []).map((source) => <div key={source.label}><span>{source.label}</span><strong><SourceLink url={source.url}>{source.source}</SourceLink></strong></div>)}
          </div>
          <p className="consensusNote">Kursmål er offentlig analytikerdekning. Kvartalsestimater og beat/miss vises bare når de kan knyttes til en verifisert offentlig meglerkilde.</p>
        </details>
      </section>
    </div>
  );
}

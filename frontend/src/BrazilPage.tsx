import { useMemo } from "react";
import { usePollingResource } from "./usePollingResource";
import "./brazil-page.css";

type Signal = { tone: "positive" | "negative" | "neutral"; label: string };
type SeriesPoint = { date: string; value: number | null };
type Metric = {
  key: string;
  label: string;
  unit: string;
  date?: string;
  value?: number | null;
  previous_value?: number | null;
  change?: number | null;
  change_1m_pct?: number | null;
  series?: SeriesPoint[];
  source?: string;
  source_url?: string;
  bemobi_impact?: string;
  signal?: Signal;
};
type FocusPoint = {
  median?: number | null;
  mean?: number | null;
  min?: number | null;
  max?: number | null;
  respondents?: number;
  survey_date?: string;
};
type FocusValues = Record<string, Record<string, FocusPoint>>;
type CalendarExpectation = {
  label: string;
  value: number;
  unit: string;
  survey_date?: string;
  respondents?: number;
  event_consensus: boolean;
  provider?: string;
};
type MarketConsensus = {
  available: boolean;
  ingested: boolean;
  coverage: string;
  provider?: string | null;
  note?: string;
};
type CalendarEvent = {
  date: string;
  name: string;
  kind: string;
  source: string;
  source_url: string;
  reference?: string | null;
  importance: string;
  bemobi_impact: string;
  expectation?: CalendarExpectation | null;
  market_consensus?: MarketConsensus | null;
};
type BrazilPayload = {
  ready: boolean;
  as_of_date: string;
  generated_at?: string;
  metrics?: Record<string, Metric>;
  focus?: {
    ready?: boolean;
    values?: FocusValues;
    source?: string;
    source_url?: string;
    note?: string;
  };
  calendar?: CalendarEvent[];
  calendar_note?: string;
  source_status?: Record<string, { ready?: boolean; error?: string }>;
  sources?: Array<{ name: string; url: string }>;
};

const REFRESH_MS = 30 * 60 * 1000;

function number(value?: number | null, digits = 2) {
  if (value == null || !Number.isFinite(value)) return "–";
  return value.toLocaleString("nb-NO", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function signed(value?: number | null, digits = 2) {
  if (value == null || !Number.isFinite(value)) return "–";
  return `${value > 0 ? "+" : ""}${number(value, digits)}`;
}

function dateLabel(value?: string | null) {
  if (!value) return "–";
  const [year, month, day] = value.slice(0, 10).split("-");
  return year && month && day ? `${day}.${month}.${year}` : value;
}

function Sparkline({ points }: { points?: SeriesPoint[] }) {
  const path = useMemo(() => {
    const values = (points ?? [])
      .filter((item): item is SeriesPoint & { value: number } => item.value != null && Number.isFinite(item.value))
      .slice(-18);
    if (values.length < 2) return null;
    const min = Math.min(...values.map((item) => item.value));
    const max = Math.max(...values.map((item) => item.value));
    const span = Math.max(max - min, 0.000001);
    const coordinates = values.map((item, index) => {
      const x = (index / (values.length - 1)) * 100;
      const y = 32 - ((item.value - min) / span) * 28;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    });
    return coordinates.join(" ");
  }, [points]);

  if (!path) return <div className="brazilSparkEmpty">Historikk mangler</div>;
  return (
    <svg aria-hidden="true" className="brazilSpark" preserveAspectRatio="none" viewBox="0 0 100 36">
      <polyline fill="none" points={path} stroke="currentColor" strokeWidth="1.8" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

function MetricCard({ metric }: { metric?: Metric }) {
  if (!metric) {
    return (
      <article className="card brazilMetricCard mutedCard">
        <span className="label">MAKRO</span>
        <strong>Datagrunnlag mangler</strong>
      </article>
    );
  }
  const digits = metric.key === "brl_nok" ? 4 : 2;
  const secondary = metric.key === "brl_nok"
    ? `${signed(metric.change_1m_pct, 1)} % siste ~1 mnd.`
    : metric.change != null
      ? `${signed(metric.change, 2)} pp siden forrige observasjon`
      : metric.key.startsWith("ibc_")
        ? "Sesongjustert månedsendring"
        : "Siste observasjon";
  const signal = metric.signal ?? { tone: "neutral", label: "Nøytral" };
  return (
    <article className="card brazilMetricCard">
      <div className="brazilMetricTop">
        <span className="label">{metric.label.toUpperCase()}</span>
        <span className={`brazilSignal ${signal.tone}`}>{signal.label}</span>
      </div>
      <div className="brazilMetricValue">
        {number(metric.value, digits)} <small>{metric.unit}</small>
      </div>
      <div className="brazilMetricSecondary">{secondary}</div>
      <Sparkline points={metric.series} />
      <p>{metric.bemobi_impact}</p>
      <div className="brazilSourceLine">{metric.source} · {dateLabel(metric.date)}</div>
    </article>
  );
}

function FocusTable({ focus, asOfDate }: { focus?: FocusValues; asOfDate?: string }) {
  const year = Number(asOfDate?.slice(0, 4) || new Date().getFullYear());
  const rows = [
    { key: "selic", label: "Selic", unit: "%" },
    { key: "ipca", label: "IPCA", unit: "%" },
    { key: "gdp", label: "BNP", unit: "%" },
    { key: "usd_brl", label: "USD/BRL", unit: "BRL" },
  ];
  return (
    <div className="brazilTableWrap">
      <table className="brazilTable">
        <thead>
          <tr><th>Indikator</th><th>{year}</th><th>{year + 1}</th><th>Sist målt</th></tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const current = focus?.[row.key]?.[String(year)];
            const next = focus?.[row.key]?.[String(year + 1)];
            const survey = current?.survey_date ?? next?.survey_date;
            return (
              <tr key={row.key}>
                <td><strong>{row.label}</strong></td>
                <td>{number(current?.median, row.key === "usd_brl" ? 2 : 2)} {row.unit}</td>
                <td>{number(next?.median, row.key === "usd_brl" ? 2 : 2)} {row.unit}</td>
                <td>{dateLabel(survey)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function CalendarRow({ event }: { event: CalendarEvent }) {
  const consensus = event.market_consensus;
  const expectation = event.expectation;
  const externalNotIngested = consensus?.coverage === "EXTERNAL_MARKET_CONSENSUS_NOT_INGESTED";
  return (
    <article className="brazilCalendarRow">
      <div className="brazilCalendarDate">
        <strong>{dateLabel(event.date).slice(0, 5)}</strong>
        <small>{event.source}</small>
      </div>
      <div className="brazilCalendarMain">
        <div className="brazilCalendarTitle">
          <strong>{event.name}</strong>
          <span className={`brazilImportance ${event.importance.startsWith("Høy") ? "high" : "medium"}`}>{event.importance}</span>
        </div>
        {event.reference && <div className="brazilCalendarReference">Referanse: {event.reference}</div>}
        <p>{event.bemobi_impact}</p>
      </div>
      <div className="brazilCalendarExpectation">
        <span className="label">MARKEDETS FORVENTNING</span>
        {expectation ? (
          <>
            <strong>{number(expectation.value, 2)} {expectation.unit}</strong>
            <small>{expectation.label} · {expectation.provider ?? "BCB Focus"}</small>
            {expectation.respondents ? <small>{expectation.respondents} respondenter</small> : null}
          </>
        ) : externalNotIngested ? (
          <>
            <strong>–</strong>
            <small>Markedskonsensus finnes, men ikke via gratis BCB Focus-feed</small>
          </>
        ) : (
          <>
            <strong>–</strong>
            <small>{consensus?.note ?? "Hendelsesnær markedsforventning ikke tilgjengelig nå"}</small>
          </>
        )}
      </div>
    </article>
  );
}

export default function BrazilPage() {
  const { data, refreshFailed, lastUpdatedAt } = usePollingResource<BrazilPayload>("/api/brazil/dashboard", REFRESH_MS);
  const metrics = data?.metrics ?? {};
  const calendar = data?.calendar ?? [];

  if (!data && !refreshFailed) {
    return <section className="card viewFallback"><span className="label">BRASIL</span><strong>Henter makrodata …</strong></section>;
  }
  if (!data) {
    return <section className="card brazilError"><span className="label">BRASIL</span><strong>Kunne ikke hente Brasil-data</strong><p>API-et svarte ikke. Ingen NAV-data påvirkes av denne siden.</p></section>;
  }

  return (
    <div className="brazilPage">
      <section className="card brazilIntro">
        <div>
          <span className="label">BRASIL / BEMOBI</span>
          <h2>Makro som påvirker Bemobi og Otellos NAV</h2>
          <p>Renter og inflasjon driver avkastningskravet, aktivitet driver Bemobis underliggende marked, og BRL/NOK slår direkte inn i Otellos NAV.</p>
        </div>
        <div className="brazilFreshness">
          <span className="label">SIST HENTET</span>
          <strong>{lastUpdatedAt ? lastUpdatedAt.toLocaleTimeString("nb-NO", { hour: "2-digit", minute: "2-digit" }) : "–"}</strong>
          {refreshFailed && <small>Forrige data beholdt</small>}
        </div>
      </section>

      <section>
        <div className="sectionHeading">
          <div><span className="label">NÅBILDE</span><h2>Viktigste makrodrivere</h2></div>
        </div>
        <div className="brazilMetricGrid">
          <MetricCard metric={metrics.brl_nok} />
          <MetricCard metric={metrics.selic} />
          <MetricCard metric={metrics.ipca_12m} />
          <MetricCard metric={metrics.ibc_br} />
          <MetricCard metric={metrics.ibc_services} />
        </div>
      </section>

      <section className="card brazilFocusCard">
        <div className="sectionHeading compactHeading">
          <div><span className="label">BCB FOCUS</span><h2>Hva markedet venter</h2></div>
        </div>
        <p className="brazilLead">Medianforventninger fra banker, forvaltere og andre deltakere i Banco Central do Brasils Focus-undersøkelse.</p>
        <FocusTable focus={data.focus?.values} asOfDate={data.as_of_date} />
        <div className="brazilNote">{data.focus?.note ?? "Focus-data mangler akkurat nå."}</div>
      </section>

      <section className="card brazilCalendarCard">
        <div className="sectionHeading compactHeading">
          <div><span className="label">MAKROKALENDER</span><h2>Neste hendelser</h2></div>
          <span className="brazilCalendarCount">{calendar.length} hendelser</span>
        </div>
        <div className="brazilCalendarList">
          {calendar.length ? calendar.map((event) => <CalendarRow event={event} key={`${event.date}-${event.name}`} />) : <p>Ingen hendelser i perioden.</p>}
        </div>
        <div className="brazilNote">{data.calendar_note}</div>
      </section>

      <section className="card brazilMethodCard">
        <span className="label">KILDER OG METODE</span>
        <h2>Gratis, offisielle kilder</h2>
        <p>Makrotall hentes fra Banco Central do Brasil (SGS), forventninger fra BCB Focus, BRL/NOK fra Norges Bank og publiseringsdatoer fra BCB/IBGE.</p>
        <div className="brazilSources">
          {(data.sources ?? []).map((source) => <span key={source.name}>{source.name}</span>)}
        </div>
        <p className="brazilDisclaimer">BCB Focus er markedets forventninger fra banker, forvaltere og andre markedsaktører – ikke sentralbankens egen prognose. For IPCA/IPCA-15, arbeidsledighet, BNP og Copom bruker kalenderen hendelsesnære Focus-medianer når de finnes. PMS, PMC og IBC-Br har også markedskonsensus hos økonom-/bankpoller som Reuters/LSEG og Trading Economics, men disse er ikke hentet automatisk fordi vi ikke har en gratis lisensiert API-feed for dem.</p>
      </section>
    </div>
  );
}

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
  label?: string;
  value?: number | null;
  unit?: string;
  survey_date?: string;
  respondents?: number;
  event_consensus?: boolean;
  provider?: string;
  previous?: string | null;
  release_at_utc?: string | null;
  release_time_provider?: string | null;
  release_time_source_url?: string | null;
  fallback_cached?: boolean;
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

const METRIC_LABELS: Record<string, string> = {
  brl_nok: "Valutakurs for brasilianske real",
  selic: "Styringsrenten",
  ipca_12m: "Prisvekst siste 12 måneder",
  ibc_br: "Økonomisk aktivitet",
  ibc_services: "Aktivitet i tjenestenæringene",
};

const FOCUS_ROW_LABELS: Record<string, string> = {
  selic: "Styringsrenten",
  ipca: "Prisvekst",
  gdp: "Økonomisk vekst (BNP)",
  usd_brl: "Valutakurs (USD/BRL)",
};

function eventLabel(event: CalendarEvent) {
  const labels: Record<string, string> = {
    copom: "Rentebeslutning fra sentralbanken",
    inflation: event.name.includes("15") ? "Foreløpig prisvekst" : "Prisvekst",
    gdp: event.name.replace("BNP", "Økonomisk vekst (BNP)"),
    services: "Aktivitet i tjenestenæringene",
    retail: "Omsetning i detaljhandelen",
    activity: "Samlet økonomisk aktivitet",
    labor: "Arbeidsledighet",
  };
  return labels[event.kind] ?? event.name;
}

function expectationLabel(value: string) {
  return value
    .replaceAll("Focus", "Markedsundersøkelse")
    .replaceAll("Selic", "styringsrente")
    .replaceAll("IPCA", "prisvekst")
    .replaceAll("proxy", "anslag");
}

function expectationProviderLabel(expectation: CalendarExpectation) {
  if (expectation.provider === "Investing.com") return "Investing.com";
  if (expectation.provider === "BCB Focus") return "markedsundersøkelsen til Brasils sentralbank";
  return expectation.provider || "markedskilde";
}

function financialText(value?: string | null) {
  if (!value) return "";
  return value
    .replaceAll("Lavere Selic", "Lavere styringsrente")
    .replaceAll("Selic", "styringsrenten")
    .replaceAll("IBC-Br", "Målet for økonomisk aktivitet")
    .replaceAll("BCB Focus", "markedsundersøkelsen til Brasils sentralbank")
    .replaceAll("Focus-data", "data fra markedsundersøkelsen")
    .replaceAll("Focus-respons", "svar fra markedsundersøkelsen")
    .replaceAll("publisert Focus", "publiserte tall fra markedsundersøkelsen")
    .replaceAll("Focus", "markedsundersøkelsen")
    .replaceAll("estimated", "anslått")
    .replaceAll("nød-fallback", "nødløsning")
    .replaceAll("fallback", "reserveløsning")
    .replaceAll("multippel-ekspansjon", "høyere verdsettelse")
    .replaceAll("multippel", "verdsettelse");
}

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

function norwayReleaseTime(value?: string | null) {
  if (!value) return null;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;
  return new Intl.DateTimeFormat("nb-NO", {
    timeZone: "Europe/Oslo",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(parsed);
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
      ? `${signed(metric.change, 2)} prosentpoeng siden forrige observasjon`
      : metric.key.startsWith("ibc_")
        ? "Sesongjustert månedsendring"
        : "Siste observasjon";
  const signal = metric.signal ?? { tone: "neutral", label: "Nøytral" };
  const unit = metric.unit.replace("% p.a.", "% per år").replace("% m/m", "% fra måneden før");
  return (
    <article className="card brazilMetricCard">
      <div className="brazilMetricTop">
        <span className="label">{(METRIC_LABELS[metric.key] ?? metric.label).toUpperCase()}</span>
        <span className={`brazilSignal ${signal.tone}`}>{financialText(signal.label)}</span>
      </div>
      <div className="brazilMetricValue">
        {number(metric.value, digits)} <small>{unit}</small>
      </div>
      <div className="brazilMetricSecondary">{secondary}</div>
      <Sparkline points={metric.series} />
      <p>{financialText(metric.bemobi_impact)}</p>
      <div className="brazilSourceLine">{metric.source} · {dateLabel(metric.date)}</div>
    </article>
  );
}

function FocusTable({ focus, asOfDate }: { focus?: FocusValues; asOfDate?: string }) {
  const year = Number(asOfDate?.slice(0, 4) || new Date().getFullYear());
  const rows = [
    { key: "selic", unit: "%" },
    { key: "ipca", unit: "%" },
    { key: "gdp", unit: "%" },
    { key: "usd_brl", unit: "BRL" },
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
                <td><strong>{FOCUS_ROW_LABELS[row.key]}</strong></td>
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
  const hasIngestedEventConsensus = expectation?.event_consensus === true;
  const externalNotIngested = consensus?.coverage === "EXTERNAL_MARKET_CONSENSUS_NOT_INGESTED";
  const annualProxy = consensus?.coverage === "BCB_FOCUS_ANNUAL_PROXY";
  const releaseTime = norwayReleaseTime(expectation?.release_at_utc);
  return (
    <article className="brazilCalendarRow">
      <div className="brazilCalendarDate">
        <strong>{dateLabel(event.date).slice(0, 5)}</strong>
        {releaseTime ? <small><b>Norsk tid kl. {releaseTime}</b></small> : null}
        <small>{event.source}</small>
      </div>
      <div className="brazilCalendarMain">
        <div className="brazilCalendarTitle">
          <strong>{eventLabel(event)}</strong>
          <span className={`brazilImportance ${event.importance.startsWith("Høy") ? "high" : "medium"}`}>{event.importance}</span>
        </div>
        {event.reference && <div className="brazilCalendarReference">Referanse: {event.reference}</div>}
        <p>{financialText(event.bemobi_impact)}</p>
      </div>
      <div className="brazilCalendarExpectation">
        <span className="label">MARKEDETS FORVENTNING</span>
        {expectation && hasIngestedEventConsensus ? (
          <>
            <strong>{number(expectation.value, 2)}{expectation.unit ? ` ${expectation.unit}` : ""}</strong>
            <small>{expectationLabel(expectation.label || "Hendelseskonsensus")} · {expectationProviderLabel(expectation)}</small>
            {expectation.previous ? <small>Forrige: {expectation.previous}</small> : null}
            {expectation.respondents ? <small>{expectation.respondents} respondenter</small> : null}
          </>
        ) : annualProxy ? (
          <>
            <strong>–</strong>
            <small>Årsestimatet finnes i tabellen over, men brukes ikke som konsensus for denne publiseringen</small>
          </>
        ) : externalNotIngested ? (
          <>
            <strong>–</strong>
            <small>Hendelseskonsensus er ikke publisert eller tilgjengelig fra Investing.com ennå</small>
          </>
        ) : (
          <>
            <strong>–</strong>
            <small>{financialText(consensus?.note) || "Markedsforventning nær hendelsen er ikke tilgjengelig nå"}</small>
          </>
        )}
      </div>
    </article>
  );
}

export default function BrazilPage() {
  const { data, refreshFailed, lastUpdatedAt } = usePollingResource<BrazilPayload>(
    "/api/brazil/dashboard",
    REFRESH_MS,
    true,
  );
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
          <h2>Økonomien som påvirker Bemobi og Otellos verdier</h2>
          <p>Renter og prisvekst påvirker hva Bemobi verdsettes til. Aktiviteten påvirker markedet Bemobi selger i, mens valutakursen for brasilianske real slår direkte inn i Otellos verdier.</p>
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
          <div><span className="label">MARKEDSUNDERSØKELSE</span><h2>Hva markedet venter</h2></div>
        </div>
        <p className="brazilLead">Den midterste forventningen blant svarene fra banker, forvaltere og andre deltakere i undersøkelsen til Brasils sentralbank.</p>
        <FocusTable focus={data.focus?.values} asOfDate={data.as_of_date} />
        <div className="brazilNote">{financialText(data.focus?.note) || "Tall fra markedsundersøkelsen viser forventninger for hele året, ikke for én bestemt publisering."}</div>
      </section>

      <section className="card brazilCalendarCard">
        <div className="sectionHeading compactHeading">
          <div><span className="label">MAKROKALENDER</span><h2>Neste hendelser</h2></div>
          <span className="brazilCalendarCount">{calendar.length} hendelser</span>
        </div>
        <div className="brazilCalendarList">
          {calendar.length ? calendar.map((event) => <CalendarRow event={event} key={`${event.date}-${event.name}`} />) : <p>Ingen hendelser i perioden.</p>}
        </div>
        <div className="brazilNote">{financialText(data.calendar_note) || "Bekreftede datoer kommer fra brasilianske myndigheter. Framtidige anslåtte datoer må bekreftes i den offisielle kalenderen."}</div>
      </section>

      <section className="card brazilMethodCard">
        <span className="label">KILDER OG METODE</span>
        <h2>Datakilder</h2>
        <p>Økonomiske nøkkeltall og publiseringsdatoer hentes fra Brasils sentralbank og IBGE, valutakursen fra Norges Bank, mens hendelseskonsensus og publiseringstid hentes fra Investing.com når tilgjengelig.</p>
        <div className="brazilSources">
          {(data.sources ?? []).map((source) => <span key={source.name}>{source.name}</span>)}
        </div>
        <p className="brazilDisclaimer">Investing.com sitt Forecast-felt brukes som hendelseskonsensus når det finnes. Tidspunkt fra kilden behandles som UTC og konverteres automatisk til Europe/Oslo, slik at både norsk sommer- og vintertid håndteres riktig. BCB Focus brukes som sekundær hendelsesforventning der en passende serie finnes. Et årlig Focus-estimat vises aldri som konsensus for en konkret makropublisering.</p>
      </section>
    </div>
  );
}
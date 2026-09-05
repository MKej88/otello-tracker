import { useMemo } from "react";
import { usePollingResource } from "./usePollingResource";
import "./brazil-page.css";

type Tone = "positive" | "negative" | "neutral";
type Signal = { tone: Tone; label: string };
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
type FocusTrendPoint = {
  year?: number;
  current?: number | null;
  previous?: number | null;
  change?: number | null;
  change_bp?: number | null;
  current_survey_date?: string | null;
  previous_survey_date?: string | null;
};
type FocusTrend = {
  ready?: boolean;
  comparison_year?: number;
  comparison_years?: number[];
  comparisons?: Record<string, {
    ready?: boolean;
    target_date?: string;
    points?: Record<string, FocusTrendPoint>;
    points_by_year?: Record<string, Record<string, FocusTrendPoint>>;
  }>;
};
type InvestorDriver = { tone: Tone; label: string; summary: string };
type InvestorSummary = {
  tone?: Tone;
  headline?: string;
  score?: number;
  method?: string;
  drivers?: {
    valuation?: InvestorDriver;
    operations?: InvestorDriver;
    nav_fx?: InvestorDriver;
  };
  rate_path?: {
    current?: number | null;
    current_year_estimate?: number | null;
    next_year_estimate?: number | null;
    expected_change_to_current_year_bp?: number | null;
    expected_change_to_next_year_bp?: number | null;
    expected_change_current_to_next_year_bp?: number | null;
  };
};
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
};
type LatestHighMacroRelease = {
  date: string;
  release_at_utc?: string | null;
  name?: string | null;
  kind?: string | null;
  importance: "Høy";
  actual?: string | null;
  actual_value?: number | null;
  forecast?: string | null;
  forecast_value?: number | null;
  previous?: string | null;
  unit?: string | null;
  surprise?: number | null;
  bemobi_impact?: string | null;
  source?: string | null;
  source_url?: string | null;
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
  focus_trend?: FocusTrend;
  investor_summary?: InvestorSummary;
  calendar?: CalendarEvent[];
  calendar_note?: string;
  latest_high_importance_release?: LatestHighMacroRelease | null;
  sources?: Array<{ name: string; url: string }>;
};
type EconomicNavPayload = {
  ready?: boolean;
  nav_per_share?: number | null;
  composition?: Array<{
    key?: string;
    label?: string;
    per_share_nok?: number | null;
    amount_mnok?: number | null;
  }> | null;
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

function latestMacroLabel(release: LatestHighMacroRelease) {
  if (release.kind === "copom") return "Rentebeslutning fra sentralbanken";
  if (release.kind === "inflation") return release.name?.includes("15") ? "Foreløpig prisvekst" : "Prisvekst";
  return release.name || "Makropublisering";
}

function financialText(value?: string | null) {
  if (!value) return "";
  return value
    .replaceAll("Lavere Selic", "Lavere styringsrente")
    .replaceAll("Selic", "styringsrenten")
    .replaceAll("IBC-Br", "målet for økonomisk aktivitet")
    .replaceAll("BCB Focus", "markedsundersøkelsen til Brasils sentralbank")
    .replaceAll("Focus-data", "data fra markedsundersøkelsen")
    .replaceAll("Focus", "markedsundersøkelsen")
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

function signedBp(value?: number | null) {
  if (value == null || !Number.isFinite(value)) return "–";
  return `${value > 0 ? "+" : ""}${number(value, 0)} bp`;
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

function toneLabel(tone?: Tone) {
  if (tone === "positive") return "POSITIV";
  if (tone === "negative") return "NEGATIV";
  return "NØYTRAL";
}

function trendPoint(data: BrazilPayload, period: string, key: string, year?: number): FocusTrendPoint | undefined {
  const comparison = data.focus_trend?.comparisons?.[period];
  if (year != null) {
    return comparison?.points_by_year?.[String(year)]?.[key]
      ?? (data.focus_trend?.comparison_year === year ? comparison?.points?.[key] : undefined);
  }
  return comparison?.points?.[key];
}

function trendTone(point: FocusTrendPoint | undefined, positiveWhenLower: boolean) {
  const change = point?.change;
  if (change == null || !Number.isFinite(change) || change === 0) return "";
  const positive = positiveWhenLower ? change < 0 : change > 0;
  return positive ? "positive" : "negative";
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
    return values.map((item, index) => {
      const x = (index / (values.length - 1)) * 100;
      const y = 32 - ((item.value - min) / span) * 28;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    }).join(" ");
  }, [points]);

  if (!path) return <div className="brazilSparkEmpty">Historikk mangler</div>;
  return (
    <svg aria-hidden="true" className="brazilSpark" preserveAspectRatio="none" viewBox="0 0 100 36">
      <polyline fill="none" points={path} stroke="currentColor" strokeWidth="1.8" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

function MetricCard({ metric }: { metric?: Metric }) {
  if (!metric) return null;
  const digits = metric.key === "brl_nok" ? 4 : 2;
  const secondary = metric.key === "brl_nok"
    ? `${signed(metric.change_1m_pct, 1)} % siste måned`
    : metric.change != null
      ? `${signed(metric.change, 2)} pp siden forrige observasjon`
      : metric.key.startsWith("ibc_")
        ? "Sesongjustert månedsendring"
        : "Siste observasjon";
  return (
    <article className="brazilDetailMetric">
      <div className="brazilMetricTop">
        <span className="label">{(METRIC_LABELS[metric.key] ?? metric.label).toUpperCase()}</span>
        <span className={`brazilSignal ${metric.signal?.tone ?? "neutral"}`}>{financialText(metric.signal?.label) || "Nøytral"}</span>
      </div>
      <strong>{number(metric.value, digits)} <small>{metric.unit.replace("% p.a.", "% per år")}</small></strong>
      <span>{secondary}</span>
      <Sparkline points={metric.series} />
      <p>{financialText(metric.bemobi_impact)}</p>
      <small>{metric.source} · {dateLabel(metric.date)}</small>
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
        <thead><tr><th>Indikator</th><th>{year}</th><th>{year + 1}</th><th>Sist målt</th></tr></thead>
        <tbody>
          {rows.map((row) => {
            const current = focus?.[row.key]?.[String(year)];
            const next = focus?.[row.key]?.[String(year + 1)];
            return (
              <tr key={row.key}>
                <td><strong>{FOCUS_ROW_LABELS[row.key]}</strong></td>
                <td>{number(current?.median, 2)} {row.unit}</td>
                <td>{number(next?.median, 2)} {row.unit}</td>
                <td>{dateLabel(current?.survey_date ?? next?.survey_date)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function CompactEvent({ event }: { event: CalendarEvent }) {
  const releaseTime = norwayReleaseTime(event.expectation?.release_at_utc);
  const expectation = event.expectation?.event_consensus ? event.expectation : null;
  return (
    <article className="brazilCompactEvent">
      <div className="brazilCompactEventDate">
        <strong>{dateLabel(event.date).slice(0, 5)}</strong>
        {releaseTime ? <small>kl. {releaseTime}</small> : null}
      </div>
      <div>
        <div className="brazilCompactEventTitle">
          <strong>{eventLabel(event)}</strong>
          <span className={`brazilImportance ${event.importance.startsWith("Høy") ? "high" : "medium"}`}>{event.importance}</span>
        </div>
        <p>{financialText(event.bemobi_impact)}</p>
      </div>
      <div className="brazilCompactConsensus">
        <span className="label">KONSENSUS</span>
        <strong>{expectation ? `${number(expectation.value, 2)}${expectation.unit ? ` ${expectation.unit}` : ""}` : "–"}</strong>
        {expectation?.previous ? <small>Forrige: {expectation.previous}</small> : null}
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
  const { data: economicNav } = usePollingResource<EconomicNavPayload>(
    "/api/dashboard/economic",
    REFRESH_MS,
    true,
  );

  if (!data && !refreshFailed) {
    return <section className="card viewFallback"><span className="label">BRASIL</span><strong>Henter makrodata …</strong></section>;
  }
  if (!data) {
    return <section className="card brazilError"><span className="label">BRASIL</span><strong>Kunne ikke hente Brasil-data</strong><p>API-et svarte ikke. Ingen NAV-data påvirkes av denne siden.</p></section>;
  }

  const metrics = data.metrics ?? {};
  const summary = data.investor_summary;
  const ratePath = summary?.rate_path;
  const calendar = data.calendar ?? [];
  const nextEvents = calendar.slice(0, 3);
  const currentYear = Number(data.as_of_date.slice(0, 4));
  const nextYear = currentYear + 1;
  const selicCurrent30d = trendPoint(data, "30d", "selic", currentYear);
  const selicNext30d = trendPoint(data, "30d", "selic", nextYear);
  const ipcaCurrent30d = trendPoint(data, "30d", "ipca", currentYear);
  const ipcaNext30d = trendPoint(data, "30d", "ipca", nextYear);
  const gdpCurrent30d = trendPoint(data, "30d", "gdp", currentYear);
  const gdpNext30d = trendPoint(data, "30d", "gdp", nextYear);
  const bemobiNavComponent = economicNav?.composition?.find((item) => item.key === "bemobi");
  const bemobiPerShare = bemobiNavComponent?.per_share_nok ?? null;
  const brlNavImpact10 = bemobiPerShare != null && Number.isFinite(bemobiPerShare) ? bemobiPerShare * 0.10 : null;
  const brlNavImpact1 = bemobiPerShare != null && Number.isFinite(bemobiPerShare) ? bemobiPerShare * 0.01 : null;
  const bemobiNavShare = bemobiPerShare != null && economicNav?.nav_per_share != null && economicNav.nav_per_share > 0
    ? bemobiPerShare / economicNav.nav_per_share * 100
    : null;

  return (
    <div className="brazilPage">
      <section className="card brazilInvestorHero">
        <div className="brazilHeroCopy">
          <span className="label">BRASIL / BEMOBI</span>
          <div className="brazilHeroTitleRow">
            <h2>{summary?.headline || "Makrobildet i Brasil"}</h2>
            <span className={`brazilRegime ${summary?.tone ?? "neutral"}`}>{toneLabel(summary?.tone)}</span>
          </div>
          <p>Tre kanaler betyr mest for Otello: rentebanen påvirker Bemobi-verdsettelsen, aktiviteten påvirker driften og BRL/NOK slår direkte inn i NAV.</p>
        </div>
        <div className="brazilFreshness">
          <span className="label">SIST HENTET</span>
          <strong>{lastUpdatedAt ? lastUpdatedAt.toLocaleTimeString("nb-NO", { hour: "2-digit", minute: "2-digit" }) : "–"}</strong>
          <small>{refreshFailed ? "Forrige data beholdt" : dateLabel(data.as_of_date)}</small>
        </div>
      </section>

      <section className="brazilDriverGrid">
        <article className="card brazilDriverCard">
          <div className="brazilDriverHeader">
            <span className="label">RENTER</span>
            <span className={`brazilSignal ${summary?.drivers?.valuation?.tone ?? "neutral"}`}>{toneLabel(summary?.drivers?.valuation?.tone)}</span>
          </div>
          <div className="brazilRatePath brazilRatePathThree">
            <div><strong>{number(ratePath?.current, 2)} %</strong><small>I dag</small></div>
            <span>→</span>
            <div><strong>{number(ratePath?.current_year_estimate, 2)} %</strong><small>{currentYear}E</small></div>
            <span>→</span>
            <div><strong>{number(ratePath?.next_year_estimate, 2)} %</strong><small>{nextYear}E</small></div>
          </div>
          <div className="brazilRateMilestones">
            <span><strong>{signedBp(ratePath?.expected_change_to_current_year_bp)}</strong> innen årsslutt</span>
            <span><strong>{signedBp(ratePath?.expected_change_to_next_year_bp)}</strong> til utgangen av {nextYear}</span>
          </div>
          <p>{summary?.drivers?.valuation?.summary || "Rentebanen beregnes fra Selic og BCB Focus."}</p>
        </article>

        <article className="card brazilDriverCard">
          <div className="brazilDriverHeader">
            <span className="label">BRL / NOK</span>
            <span className={`brazilSignal ${summary?.drivers?.nav_fx?.tone ?? "neutral"}`}>{toneLabel(summary?.drivers?.nav_fx?.tone)}</span>
          </div>
          <div className="brazilDriverMainValue">{number(metrics.brl_nok?.value, 4)}</div>
          <div className="brazilDriverMetric">{signed(metrics.brl_nok?.change_1m_pct, 1)} % siste måned</div>
          <div className="brazilNavSensitivity">
            <span>+10 % BRL</span>
            <strong>{brlNavImpact10 == null ? "–" : `${signed(brlNavImpact10, 2)} kr NAV/OTEC`}</strong>
          </div>
          <p>{brlNavImpact1 == null ? summary?.drivers?.nav_fx?.summary : `+1 % BRL tilsvarer om lag ${signed(brlNavImpact1, 2)} kr NAV per OTEC-aksje, alt annet likt.`}</p>
        </article>

        <article className="card brazilDriverCard">
          <div className="brazilDriverHeader">
            <span className="label">AKTIVITET</span>
            <span className={`brazilSignal ${summary?.drivers?.operations?.tone ?? "neutral"}`}>{toneLabel(summary?.drivers?.operations?.tone)}</span>
          </div>
          <div className="brazilActivityPair">
            <div><span>IBC-Br</span><strong>{signed(metrics.ibc_br?.value, 2)} %</strong></div>
            <div><span>Tjenester</span><strong>{signed(metrics.ibc_services?.value, 2)} %</strong></div>
          </div>
          <p>{summary?.drivers?.operations?.summary || "Aktivitetssignalene viser etterspørselsbildet Bemobi opererer i."}</p>
        </article>
      </section>

      <section className="card brazilChangeCard">
        <div className="sectionHeading compactHeading">
          <div><span className="label">HVA HAR ENDRET SEG?</span><h2>Siste måned</h2></div>
          <small>Focus-endringer sammenlignes med samme offisielle BCB-serier rundt 30 dager tidligere.</small>
        </div>
        <div className="brazilChangeLayout">
          <div className="brazilChangeTableWrap">
            <table className="brazilChangeTable">
              <thead><tr><th>Indikator</th><th>{currentYear}E</th><th>{nextYear}E</th></tr></thead>
              <tbody>
                <tr>
                  <td>Selic</td>
                  <td><strong className={trendTone(selicCurrent30d, true)}>{signedBp(selicCurrent30d?.change_bp)}</strong></td>
                  <td><strong className={trendTone(selicNext30d, true)}>{signedBp(selicNext30d?.change_bp)}</strong></td>
                </tr>
                <tr>
                  <td>IPCA</td>
                  <td><strong className={trendTone(ipcaCurrent30d, true)}>{signedBp(ipcaCurrent30d?.change_bp)}</strong></td>
                  <td><strong className={trendTone(ipcaNext30d, true)}>{signedBp(ipcaNext30d?.change_bp)}</strong></td>
                </tr>
                <tr>
                  <td>BNP</td>
                  <td><strong className={trendTone(gdpCurrent30d, false)}>{gdpCurrent30d?.change == null ? "–" : `${signed(gdpCurrent30d.change, 2)} pp`}</strong></td>
                  <td><strong className={trendTone(gdpNext30d, false)}>{gdpNext30d?.change == null ? "–" : `${signed(gdpNext30d.change, 2)} pp`}</strong></td>
                </tr>
              </tbody>
            </table>
          </div>
          <div className="brazilChangeFx">
            <span>BRL/NOK · siste måned</span>
            <strong className={(metrics.brl_nok?.change_1m_pct ?? 0) > 0 ? "positive" : (metrics.brl_nok?.change_1m_pct ?? 0) < 0 ? "negative" : ""}>{signed(metrics.brl_nok?.change_1m_pct, 1)} %</strong>
          </div>
        </div>
      </section>

      {data.latest_high_importance_release ? (
        <section className="card brazilLatestCompact">
          <div className="brazilLatestCompactTitle">
            <div><span className="label">SISTE VIKTIGE MAKROTALL</span><h2>{latestMacroLabel(data.latest_high_importance_release)}</h2></div>
            <span>{dateLabel(data.latest_high_importance_release.date)}</span>
          </div>
          <div className="brazilLatestCompactValues">
            <div><span>Faktisk</span><strong>{data.latest_high_importance_release.actual || "–"}</strong></div>
            <div><span>Forventet</span><strong>{data.latest_high_importance_release.forecast || "–"}</strong></div>
            <div><span>Avvik</span><strong>{data.latest_high_importance_release.surprise == null ? "–" : `${signed(data.latest_high_importance_release.surprise, 2)} pp`}</strong></div>
          </div>
          <p>{financialText(data.latest_high_importance_release.bemobi_impact) || "Ingen særskilt Bemobi-vurdering er knyttet til publiseringen."}</p>
        </section>
      ) : null}

      <section className="card brazilNextEventsCard">
        <div className="sectionHeading compactHeading">
          <div><span className="label">NESTE VIKTIGE HENDELSER</span><h2>Makrokalender</h2></div>
          <span className="brazilCalendarCount">3 nærmeste</span>
        </div>
        <div className="brazilCompactEventList">
          {nextEvents.length ? nextEvents.map((event) => <CompactEvent event={event} key={`${event.date}-${event.name}`} />) : <p>Ingen kommende hendelser i perioden.</p>}
        </div>
      </section>

      <section className="brazilDetailsStack">
        <details className="card brazilDetailBlock">
          <summary><span><span className="label">MARKEDSFORVENTNINGER</span><strong>BCB Focus</strong></span><span>Vis detaljer</span></summary>
          <div className="brazilDetailBody">
            <p>Medianforventningen blant banker, forvaltere og andre deltakere i markedsundersøkelsen til Brasils sentralbank.</p>
            <FocusTable focus={data.focus?.values} asOfDate={data.as_of_date} />
          </div>
        </details>

        <details className="card brazilDetailBlock">
          <summary><span><span className="label">ALLE INDIKATORER</span><strong>Makrodetaljer og historikk</strong></span><span>Vis detaljer</span></summary>
          <div className="brazilDetailMetricGrid">
            <MetricCard metric={metrics.brl_nok} />
            <MetricCard metric={metrics.selic} />
            <MetricCard metric={metrics.ipca_12m} />
            <MetricCard metric={metrics.ibc_br} />
            <MetricCard metric={metrics.ibc_services} />
          </div>
        </details>

        <details className="card brazilDetailBlock">
          <summary><span><span className="label">FULL MAKROKALENDER</span><strong>{calendar.length} kommende hendelser</strong></span><span>Vis detaljer</span></summary>
          <div className="brazilCompactEventList brazilFullCalendar">
            {calendar.map((event) => <CompactEvent event={event} key={`${event.date}-${event.name}`} />)}
          </div>
        </details>

        <details className="card brazilDetailBlock">
          <summary><span><span className="label">KILDER OG METODE</span><strong>Datagrunnlag</strong></span><span>Vis detaljer</span></summary>
          <div className="brazilDetailBody">
            <p>Selic, inflasjon og aktivitetsserier hentes fra Brasils sentralbank, Focus-forventninger fra BCB Olinda, publiseringsdatoer fra BCB/IBGE og BRL/NOK fra Norges Bank. Investing.com brukes bare som sekundær kilde for hendelseskonsensus og publiseringstid når dette finnes.</p>
            <p>Brasil-statusen er regelbasert og bruker tre transparente kanaler: rentebane, aktivitet og BRL/NOK. Den er ikke en AI-score. BRL-sensitiviteten bruker den samme Bemobi-komponenten som investor-NAV og viser isolert valutaeffekt, alt annet likt.</p>
            {bemobiNavShare != null ? <p>Bemobi utgjør nå omtrent <strong>{number(bemobiNavShare, 1)} %</strong> av investor-NAV før andre samtidige markedsbevegelser.</p> : null}
            <div className="brazilSources">{(data.sources ?? []).map((source) => <span key={source.name}>{source.name}</span>)}</div>
          </div>
        </details>
      </section>
    </div>
  );
}

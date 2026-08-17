import { useEffect, useMemo, useState } from "react";

type ChangeSet = {
  nav_pct: number | null;
  otec_pct: number | null;
  discount_pp: number | null;
  bmob3_pct: number | null;
  brl_nok_pct: number | null;
  cash_pct: number | null;
};

type Buyback = {
  trade_date: string;
  shares: number;
  avg_price_nok: string;
  amount_nok: string;
  treasury_shares_after: number | null;
  cumulative_program_shares: number | null;
  cumulative_program_amount_nok: string | null;
};

type BuybackForecast = {
  ready: boolean;
  status: string;
  forecast_week?: {
    from: string;
    to: string;
    expected_trading_days: number;
  };
  volume_model?: {
    adv20_shares: number;
    safe_harbour_share: number;
    week_start_capacity_estimate_shares: number;
    volume_through: string;
    volume_source_quality: string;
    note: string;
  };
  price_model?: {
    latest_close_nok: number | null;
    program_cap_nok: number | null;
    headroom_pct: number | null;
    state: string;
  };
  estimate?: {
    base_case_shares: number;
    low_shares: number;
    high_shares: number;
    utilization_factor: number;
    confidence: string;
    warning: string | null;
  };
  active_program_backtest?: {
    weeks: number;
    median_ape_pct?: number | null;
    wmape_pct?: number | null;
    within_10_pct?: number | null;
    within_20_pct?: number | null;
  };
};

type Summary = {
  ready: boolean;
  data_status: string;
  model_scope?: string;
  calculation_version?: string;
  as_of_date?: string;
  nav_per_share?: number | null;
  otec_price?: number | null;
  nav_discount_pct?: number | null;
  bmob3_price?: number | null;
  brl_nok?: number | null;
  estimated_cash_mnok?: number | null;
  other_net_assets_mnok?: number | null;
  bemobi_value_mnok?: number | null;
  bemobi_shares?: number | null;
  bemobi_ownership_pct?: number | null;
  shares_outstanding?: number | null;
  cash_quality?: string | null;
  cash_calibration_quality?: string | null;
  share_count_quality?: string | null;
  otec_price_quality?: string | null;
  otec_price_source?: string | null;
  bmob3_price_quality?: string | null;
  bmob3_price_source?: string | null;
  quality_notes?: string | null;
  changes?: ChangeSet;
  latest_buyback?: Buyback | null;
  message?: string;
};

type HistoryPoint = {
  date: string;
  nav_per_share: number;
  otec_price: number;
  discount_pct: number;
  cash_mnok: number;
  other_net_assets_mnok?: number;
  status: string;
};

type History = {
  ready: boolean;
  data_status: string;
  model_scope?: string;
  from?: string | null;
  to?: string | null;
  average_discount_pct?: number | null;
  points: HistoryPoint[];
};

const initialSummary: Summary = { ready: false, data_status: "loading" };
const initialHistory: History = { ready: false, data_status: "loading", points: [] };
const initialForecast: BuybackForecast = { ready: false, status: "loading" };

const menu = [
  "Oversikt",
  "NAV",
  "Historikk",
  "Tilbakekjøp",
  "Bemobi",
  "Consensus",
  "Aksjonærer",
  "Nyheter",
  "Innstillinger"
];

const number = new Intl.NumberFormat("nb-NO", { maximumFractionDigits: 2 });
const integer = new Intl.NumberFormat("nb-NO", { maximumFractionDigits: 0 });

function value(value: number | null | undefined, digits = 2) {
  if (value == null || !Number.isFinite(value)) return "–";
  return value.toLocaleString("nb-NO", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits
  });
}

function dateLabel(value?: string | null) {
  if (!value) return "–";
  const [year, month, day] = value.split("-");
  return `${day}.${month}.${year}`;
}

function changeLabel(change: number | null | undefined, unit = "%") {
  if (change == null || !Number.isFinite(change)) return "Ingen sammenligning";
  const prefix = change > 0 ? "+" : "";
  return `${prefix}${change.toLocaleString("nb-NO", { maximumFractionDigits: 2 })} ${unit}`;
}

function changeTone(change: number | null | undefined, invert = false) {
  if (change == null || change === 0) return "neutral";
  const positive = invert ? change < 0 : change > 0;
  return positive ? "positive" : "negative";
}

function polyline(values: Array<number | null>, shared?: { min: number; max: number }) {
  const valid = values.filter((item): item is number => item != null && Number.isFinite(item));
  if (!valid.length) return "";
  const min = shared?.min ?? Math.min(...valid);
  const max = shared?.max ?? Math.max(...valid);
  const spread = max - min || 1;
  return values
    .map((item, index) => {
      if (item == null || !Number.isFinite(item)) return null;
      const x = values.length === 1 ? 50 : 3 + (index / (values.length - 1)) * 94;
      const y = 37 - ((item - min) / spread) * 32;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .filter(Boolean)
    .join(" ");
}

function NavPriceChart({ points }: { points: HistoryPoint[] }) {
  if (points.length < 2) return <div className="chartEmpty">Venter på historisk NAV-data</div>;
  const nav = points.map((item) => item.nav_per_share);
  const price = points.map((item) => item.otec_price);
  const combined = [...nav, ...price].filter(Number.isFinite);
  const domain = { min: Math.min(...combined), max: Math.max(...combined) };
  return (
    <div className="realChart">
      <svg viewBox="0 0 100 42" preserveAspectRatio="none" aria-label="NAV mot OTEC-kurs">
        {[9, 18, 27, 36].map((y) => <line className="gridLine" x1="0" x2="100" y1={y} y2={y} key={y} />)}
        <polyline className="chartLine navSeries" points={polyline(nav, domain)} />
        <polyline className="chartLine priceSeries" points={polyline(price, domain)} />
      </svg>
      <div className="legend"><span className="navLegend">NAV/aksje</span><span className="priceLegend">OTEC</span></div>
      <div className="chartDates"><span>{dateLabel(points[0].date)}</span><span>{dateLabel(points.at(-1)?.date)}</span></div>
    </div>
  );
}

function DiscountChart({ points, average }: { points: HistoryPoint[]; average?: number | null }) {
  if (points.length < 2) return <div className="chartEmpty">Venter på historisk rabattdata</div>;
  const discounts = points.map((item) => item.discount_pct);
  const valid = discounts.filter(Number.isFinite);
  const domain = { min: Math.min(...valid, average ?? Infinity), max: Math.max(...valid, average ?? -Infinity) };
  const avgY = average == null || domain.max === domain.min
    ? null
    : 37 - ((average - domain.min) / (domain.max - domain.min)) * 32;
  return (
    <div className="realChart">
      <svg viewBox="0 0 100 42" preserveAspectRatio="none" aria-label="Historisk NAV-rabatt">
        {[9, 18, 27, 36].map((y) => <line className="gridLine" x1="0" x2="100" y1={y} y2={y} key={y} />)}
        {avgY != null && <line className="averageSeries" x1="3" x2="97" y1={avgY} y2={avgY} />}
        <polyline className="chartLine discountSeries" points={polyline(discounts, domain)} />
      </svg>
      <div className="legend"><span className="discountLegend">NAV-rabatt</span><span className="averageLegend">Snitt {average == null ? "–" : `${value(average, 1)} %`}</span></div>
      <div className="chartDates"><span>{dateLabel(points[0].date)}</span><span>{dateLabel(points.at(-1)?.date)}</span></div>
    </div>
  );
}

export default function App() {
  const [summary, setSummary] = useState<Summary>(initialSummary);
  const [history, setHistory] = useState<History>(initialHistory);
  const [forecast, setForecast] = useState<BuybackForecast>(initialForecast);
  const [apiOk, setApiOk] = useState(false);

  useEffect(() => {
    Promise.all([
      fetch("/api/dashboard/summary").then((response) => {
        if (!response.ok) throw new Error("Summary API-feil");
        return response.json() as Promise<Summary>;
      }),
      fetch("/api/dashboard/history?days=365&max_points=300").then((response) => {
        if (!response.ok) throw new Error("History API-feil");
        return response.json() as Promise<History>;
      }),
      fetch("/api/buybacks/forecast").then((response) => {
        if (!response.ok) return initialForecast;
        return response.json() as Promise<BuybackForecast>;
      }).catch(() => initialForecast)
    ])
      .then(([summaryData, historyData, forecastData]) => {
        setSummary(summaryData);
        setHistory(historyData);
        setForecast(forecastData);
        setApiOk(true);
      })
      .catch(() => {
        setApiOk(false);
        setSummary({ ready: false, data_status: "error", message: "Kunne ikke hente dashboarddata." });
      });
  }, []);

  const changes = summary.changes;
  const cards = useMemo(() => [
    { label: "NAV/aksje", value: summary.ready ? `${value(summary.nav_per_share)} kr` : "–", change: changes?.nav_pct, unit: "%" },
    { label: "OTEC kurs", value: summary.ready ? `${value(summary.otec_price)} kr` : "–", change: changes?.otec_pct, unit: "%" },
    { label: "Rabatt til NAV", value: summary.ready ? `${value(summary.nav_discount_pct, 1)} %` : "–", change: changes?.discount_pp, unit: "pp", invert: true },
    { label: "BMOB3", value: summary.ready ? `R$ ${value(summary.bmob3_price)}` : "–", change: changes?.bmob3_pct, unit: "%" },
    { label: "BRL/NOK", value: summary.ready ? value(summary.brl_nok, 3) : "–", change: changes?.brl_nok_pct, unit: "%" },
    { label: "Estimert cash", value: summary.ready ? `${value(summary.estimated_cash_mnok, 1)}m` : "–", change: changes?.cash_pct, unit: "%" }
  ], [summary, changes]);

  const degraded = summary.data_status === "DEGRADED" || summary.cash_quality === "FORECAST_PARTIAL";
  const estimated = !degraded && summary.data_status === "ESTIMATED";
  const qualityWarning = degraded || estimated;
  const latestBuyback = summary.latest_buyback;
  const ownership = summary.bemobi_ownership_pct ?? 0;
  const scope = summary.model_scope ?? "CORE";
  const navStatusLabel = degraded ? "DEGRADERT" : estimated ? "ESTIMERT" : summary.ready ? "KLAR" : "VENTER";
  const forecastEstimate = forecast.estimate;
  const forecastWeek = forecast.forecast_week;
  const forecastConfidence = forecastEstimate?.confidence ?? "VENTER";

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brandMark">O</span>
          <div><strong>Otello</strong><small>Investorverktøy</small></div>
        </div>
        <nav>
          {menu.map((item, index) => (
            <button className={index === 0 ? "navItem active" : "navItem"} key={item}>
              <span className="navDot" />{item}
            </button>
          ))}
        </nav>
        <div className="sidebarFooter">
          <span className={apiOk ? "statusDot ok" : "statusDot"} />
          API {apiOk ? "tilkoblet" : "venter"}
        </div>
      </aside>

      <main className="main">
        <header>
          <div><p className="eyebrow">OTELLO / BEMOBI</p><h1>Otello NAV Dashboard</h1></div>
          <div className="updated">
            <span className={apiOk && summary.ready ? "statusDot ok" : "statusDot"} />
            {summary.ready ? `Data ${dateLabel(summary.as_of_date)} · ${scope}` : "Venter på NAV-data"}
          </div>
        </header>

        {qualityWarning && (
          <div className="modelWarning">
            <strong>{degraded ? "NAV har redusert datakvalitet." : "NAV inneholder estimerte komponenter."}</strong>
            <span>
              {degraded
                ? "Minst én viktig input er ufullstendig, gammel eller bygger på en usikker modell. Se modellstatus før NAV brukes som beslutningsgrunnlag."
                : "Mellom rapportdatoer brukes forankrede estimater for blant annet cash og øvrige nettoeiendeler. Rapporterte ankere beholdes separat."}
            </span>
          </div>
        )}
        {!summary.ready && summary.message && <div className="modelWarning neutralWarning">{summary.message}</div>}

        <section className="kpiGrid">
          {cards.map((card) => (
            <article className="card kpi" key={card.label}>
              <span className="label">{card.label}</span>
              <strong>{card.value}</strong>
              <span className={`change ${changeTone(card.change, card.invert)}`}>
                {changeLabel(card.change, card.unit)}
              </span>
            </article>
          ))}
        </section>

        <section className="chartGrid">
          <article className="card chart">
            <div className="cardHeader">
              <div><span className="label">Markeds-NAV</span><h2>{scope} NAV vs OTEC</h2></div>
              <span className="pill">1 ÅR</span>
            </div>
            <NavPriceChart points={history.points} />
          </article>

          <article className="card chart">
            <div className="cardHeader">
              <div><span className="label">Verdsettelse</span><h2>Historisk NAV-rabatt</h2></div>
              <span className="pill">{summary.ready ? `${value(summary.nav_discount_pct, 1)} %` : "–"}</span>
            </div>
            <DiscountChart points={history.points} average={history.average_discount_pct} />
          </article>
        </section>

        <section className="lowerGrid">
          <article className="card">
            <div className="cardHeader">
              <div><span className="label">Kapitalallokering</span><h2>Tilbakekjøp</h2></div>
              <span className="pill muted">{forecast.ready ? forecastConfidence : latestBuyback ? dateLabel(latestBuyback.trade_date) : "Ingen data"}</span>
            </div>
            <div className="placeholderRows">
              <div><span>Siste uke</span><strong>{latestBuyback ? `${integer.format(latestBuyback.shares)} aksjer` : "–"}</strong></div>
              <div>
                <span>{forecastWeek ? `Est. ${dateLabel(forecastWeek.from)}–${dateLabel(forecastWeek.to)}` : "Neste uke"}</span>
                <strong>{forecastEstimate ? `${integer.format(forecastEstimate.base_case_shares)} aksjer` : "–"}</strong>
              </div>
              <div><span>Estimatintervall</span><strong>{forecastEstimate ? `${integer.format(forecastEstimate.low_shares)}–${integer.format(forecastEstimate.high_shares)}` : "–"}</strong></div>
              <div><span>20d snittvolum</span><strong>{forecast.volume_model ? integer.format(forecast.volume_model.adv20_shares) : "–"}</strong></div>
              <div><span>Programgrense</span><strong>{forecast.price_model?.program_cap_nok != null ? `${value(forecast.price_model.program_cap_nok)} kr` : "–"}</strong></div>
              {forecastEstimate?.warning && <div><span>Varsel</span><strong>{forecastEstimate.warning}</strong></div>}
            </div>
          </article>

          <article className="card">
            <div className="cardHeader"><div><span className="label">Underliggende verdi</span><h2>Bemobi-eksponering</h2></div></div>
            <div className="exposure">
              <div className="donut" style={{ background: `conic-gradient(#3f8cff 0 ${Math.max(0, Math.min(100, ownership))}%, #182b45 ${Math.max(0, Math.min(100, ownership))}% 100%)` }}>
                <span>{summary.ready ? `${value(ownership, 1)}%` : "–"}</span>
              </div>
              <div className="placeholderRows grow">
                <div><span>BMOB3-aksjer</span><strong>{summary.bemobi_shares != null ? integer.format(summary.bemobi_shares) : "–"}</strong></div>
                <div><span>BMOB3-kurs</span><strong>{summary.bmob3_price != null ? `R$ ${value(summary.bmob3_price)}` : "–"}</strong></div>
                <div><span>Markedsverdi</span><strong>{summary.bemobi_value_mnok != null ? `${number.format(summary.bemobi_value_mnok)}m kr` : "–"}</strong></div>
              </div>
            </div>
          </article>

          <article className="card">
            <div className="cardHeader"><div><span className="label">System</span><h2>Modellstatus</h2></div></div>
            <div className="sourceList">
              <div><span>{scope} NAV</span><span className={qualityWarning ? "sourceWarn" : summary.ready ? "sourceOk" : "sourceWait"}>{navStatusLabel}</span></div>
              {scope === "FULL" && <div><span>Øvrige nettoeiendeler</span><span className="sourceOk">{summary.other_net_assets_mnok != null ? `${value(summary.other_net_assets_mnok, 1)}m` : "–"}</span></div>}
              <div><span>Cash</span><span className={qualityWarning ? "sourceWarn" : "sourceOk"}>{summary.cash_quality ?? "–"}</span></div>
              {summary.cash_calibration_quality && <div><span>Cash-avstemming</span><span className={summary.cash_calibration_quality === "HIGH_RESIDUAL" ? "sourceWarn" : "sourceOk"}>{summary.cash_calibration_quality}</span></div>}
              {summary.share_count_quality && <div><span>Aksjetall</span><span className={summary.share_count_quality === "POTENTIALLY_STALE" ? "sourceWarn" : "sourceOk"}>{summary.share_count_quality}</span></div>}
              <div><span>OTEC</span><span className="sourceOk">{summary.otec_price_source ?? "–"}</span></div>
              <div><span>BMOB3</span><span className="sourceOk">{summary.bmob3_price_source ?? "–"}</span></div>
              <div><span>Buyback-prognose</span><span className={forecast.ready ? "sourceOk" : "sourceWait"}>{forecast.ready ? forecastConfidence : "VENTER"}</span></div>
            </div>
          </article>
        </section>
      </main>
    </div>
  );
}

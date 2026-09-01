import MarketQuotePanel from "./MarketQuotePanel";
import { usePollingResource } from "./usePollingResource";
import { formatDate, formatDateTime, formatInteger, formatNumber } from "./uiFormat";

const REFRESH_MS = 2 * 60 * 1000;

type Summary = {
  ready: boolean;
  as_of_date?: string;
  otec_price?: number | null;
  brl_nok?: number | null;
  brl_nok_insights?: {
    daily_pct?: number | null;
    month_pct?: number | null;
    quarter_pct?: number | null;
    quarter_label?: string | null;
    nav_effect_1m_per_share_nok?: number | null;
    range_1y?: {
      low?: number | null;
      high?: number | null;
      position_pct?: number | null;
    };
  };
  nav_discount_insights?: {
    nav_per_share?: number | null;
    share_price?: number | null;
    discount_pct?: number | null;
    upside_to_nav_pct?: number | null;
    month_change_pp?: number | null;
    median_1y_pct?: number | null;
    range_1y?: { low?: number | null; high?: number | null; position_pct?: number | null };
  };
  bemobi_value_mnok?: number | null;
  bemobi_ownership_pct?: number | null;
  market_timestamps?: {
    brl_nok?: { date?: string | null };
  };
  latest_buyback?: { trade_date?: string; shares?: number } | null;
};

function signed(value: number | null | undefined, digits: number, suffix: string): string {
  if (value == null || !Number.isFinite(value)) return "—";
  const prefix = value > 0 ? "+" : "";
  return `${prefix}${formatNumber(value, digits)}${suffix}`;
}

function tone(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value) || value === 0) return "neutral";
  return value > 0 ? "positive" : "negative";
}

type EstimatedNav = {
  ready: boolean;
  as_of_date?: string;
  calculated_at?: string | null;
  nav_per_share?: number | null;
  discount_pct?: number | null;
  economic_cash_mnok?: number | null;
};

type Forecast = {
  ready: boolean;
  status?: string;
  forecast_week?: { from?: string; to?: string };
  estimate?: { base_case_shares?: number; low_shares?: number; high_shares?: number };
};

type DiscountHistory = {
  estimated?: {
    ready: boolean;
    statistics?: {
      median_discount_pct?: number | null;
      minimum_discount_pct?: number | null;
      maximum_discount_pct?: number | null;
    };
  };
};

export default function OverviewPage() {
  const { data: summary, refreshFailed: summaryRefreshFailed } = usePollingResource<Summary>(
    "/api/dashboard/summary",
    REFRESH_MS,
    true,
  );
  const { data: nav, refreshFailed } = usePollingResource<EstimatedNav>(
    "/api/dashboard/economic",
    REFRESH_MS,
    true,
  );
  const { data: forecast } = usePollingResource<Forecast>(
    "/api/buybacks/forecast",
    REFRESH_MS,
    true,
  );
  const { data: history } = usePollingResource<DiscountHistory>(
    "/api/dashboard/discount-history?days=365&max_points=72",
    REFRESH_MS,
    true,
  );
  const brlNokDate = summary?.market_timestamps?.brl_nok?.date;
  const brl = summary?.brl_nok_insights;
  const range = brl?.range_1y;
  const discount = summary?.nav_discount_insights;
  const historyStatistics = history?.estimated?.statistics;
  const discountLow = historyStatistics?.minimum_discount_pct;
  const discountHigh = historyStatistics?.maximum_discount_pct;
  const hasDiscountRange = discountLow != null && discountHigh != null;
  const discountPosition = hasDiscountRange && nav?.discount_pct != null
    ? discountHigh === discountLow
      ? 50
      : ((nav.discount_pct - discountLow) / (discountHigh - discountLow)) * 100
    : null;
  const hasRange = range?.low != null && range?.high != null;
  const brlNokStatus = summaryRefreshFailed
    ? summary
      ? `Viser siste gode kurs ${formatDate(brlNokDate)}`
      : "Kurs utilgjengelig"
    : `Siste kurs ${formatDate(brlNokDate)}`;

  return (
    <div className="investorPage overviewV2">
      <section className="estimatedHero card">
        <div>
          <span className="label">NAV</span>
          <h2>{nav?.ready ? `${formatNumber(nav.nav_per_share)} kr` : "Laster …"}</h2>
          <p>
            Dagens beste estimat på verdien per Otello-aksje basert på markedsverdier,
            valuta, kontantbeholdning, drift og opsjonsoppgjør.
          </p>
        </div>
        <div className="estimatedHeroSide">
          <div><span>OTEC</span><strong>{formatNumber(summary?.otec_price)} kr</strong></div>
          <div><span>Rabatt til NAV</span><strong>{formatNumber(nav?.discount_pct, 1)} %</strong></div>
          <small>Sist oppdatert {formatDateTime(nav?.calculated_at)}</small>
          <small>Kontrolleres hvert 30. minutt</small>
          {refreshFailed && <small>Viser siste gode data</small>}
        </div>
      </section>

      <section className="kpiGrid overviewKpiGrid">
        <article className="card kpi brlInsightCard">
          <span className="label">BRL/NOK</span>
          <div className="brlCurrent">
            <strong>{formatNumber(summary?.brl_nok, 4)}</strong>
            <strong className={tone(brl?.daily_pct)}>{signed(brl?.daily_pct, 2, " %")}</strong>
          </div>
          <small>{brlNokStatus}</small>
          <div className="brlRows">
            <div><span>1 mnd</span><b className={tone(brl?.month_pct)}>{signed(brl?.month_pct, 1, " %")}</b></div>
            <div><span>{brl?.quarter_label ? `Siden ${brl.quarter_label}` : "Siden kvartal"}</span><b className={tone(brl?.quarter_pct)}>{signed(brl?.quarter_pct, 1, " %")}</b></div>
            <div><span>NAV-effekt 1 mnd</span><b className={tone(brl?.nav_effect_1m_per_share_nok)}>{signed(brl?.nav_effect_1m_per_share_nok, 2, " kr/aksje")}</b></div>
          </div>
          <div className="brlRange">
            <span>1 år</span>
            <span>{hasRange ? formatNumber(range?.low, 2) : "—"}</span>
            <div className="brlRangeTrack" aria-label="Posisjon i ettårsintervallet">
              {range?.position_pct != null && Number.isFinite(range.position_pct) && (
                <i style={{ left: `${Math.max(0, Math.min(100, range.position_pct))}%` }} />
              )}
            </div>
            <span>{hasRange ? formatNumber(range?.high, 2) : "—"}</span>
          </div>
          <small className="brlExplanation">Sterkere BRL = positivt for Otello NAV</small>
        </article>
        <article className="card kpi navDiscountCard">
          <span className="label">NAV-rabatt</span>
          <strong>{nav?.discount_pct == null ? "—" : `${formatNumber(nav.discount_pct, 1)} %`}</strong>
          <div className="brlRows navDiscountRows">
            <div><span>NAV / aksje</span><b>{nav?.nav_per_share == null ? "—" : `${formatNumber(nav.nav_per_share, 2)} kr`}</b></div>
            <div><span>Aksjekurs</span><b>{summary?.otec_price == null ? "—" : `${formatNumber(summary.otec_price, 2)} kr`}</b></div>
            <div><span>Oppside til NAV</span><b className={tone(nav?.nav_per_share != null && summary?.otec_price != null ? (nav.nav_per_share / summary.otec_price - 1) * 100 : null)}>{signed(nav?.nav_per_share != null && summary?.otec_price != null ? (nav.nav_per_share / summary.otec_price - 1) * 100 : null, 1, " %")}</b></div>
            <div><span>1 mnd</span><b className={tone(discount?.month_change_pp == null ? null : -discount.month_change_pp)}>{signed(discount?.month_change_pp, 1, " pp")}</b></div>
            <div><span>1 år median</span><b>{historyStatistics?.median_discount_pct == null ? "—" : `${formatNumber(historyStatistics.median_discount_pct, 1)} %`}</b></div>
          </div>
          <div className="brlRange navDiscountRange">
            <span>1 år</span>
            <span>{hasDiscountRange ? `${formatNumber(discountLow, 1)} %` : "—"}</span>
            <div className="brlRangeTrack" aria-label="Dagens rabatt i ettårsintervallet">
              {discountPosition != null && Number.isFinite(discountPosition) && (
                <i style={{ left: `${Math.max(0, Math.min(100, discountPosition))}%` }} />
              )}
            </div>
            <span>{hasDiscountRange ? `${formatNumber(discountHigh, 1)} %` : "—"}</span>
          </div>
        </article>
        <article className="card kpi"><span className="label">Bemobi-verdi</span><strong>{formatNumber(summary?.bemobi_value_mnok, 1)} mill. kr</strong></article>
      </section>

      <section className="overviewGrid">
        <article className="card">
          <div className="cardHeader"><div><span className="label">Kapitalallokering</span><h2>Tilbakekjøpsprogram</h2></div></div>
          <div className="placeholderRows overviewBuybackRows">
            <div>
              <span>Siste rapporterte kjøp</span>
              <span className="overviewBuybackValue">
                <strong>{formatInteger(summary?.latest_buyback?.shares)} aksjer</strong>
                <small>{formatDate(summary?.latest_buyback?.trade_date)}</small>
              </span>
            </div>
            <div>
              <span>Neste uke – baseestimat</span>
              <span className="overviewBuybackValue">
                <strong>{formatInteger(forecast?.estimate?.base_case_shares)} aksjer</strong>
                <small>{formatDate(forecast?.forecast_week?.from)}–{formatDate(forecast?.forecast_week?.to)}</small>
              </span>
            </div>
            <div><span>Estimatintervall</span><strong>{formatInteger(forecast?.estimate?.low_shares)}–{formatInteger(forecast?.estimate?.high_shares)}</strong></div>
          </div>
        </article>

        <article className="card">
          <div className="cardHeader"><div><span className="label">Underliggende verdi</span><h2>Bemobi</h2></div></div>
          <div className="placeholderRows">
            <div><span>Verdi for Otello</span><strong>{formatNumber(summary?.bemobi_value_mnok, 1)} mill. kr</strong></div>
            <div><span>Otellos eierandel</span><strong>{formatNumber(summary?.bemobi_ownership_pct, 1)} %</strong></div>
            <div><span>Estimert kontantbeholdning</span><strong>{formatNumber(nav?.economic_cash_mnok, 1)} mill. kr</strong></div>
          </div>
        </article>
      </section>

      <MarketQuotePanel />
    </div>
  );
}

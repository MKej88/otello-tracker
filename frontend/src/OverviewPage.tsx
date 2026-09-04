import type { ReactNode } from "react";

import {
  MarketQuotePanelWithData,
  type MarketQuotePayload,
  type Quote,
} from "./MarketQuotePanel";
import {
  freshnessStatus,
  freshnessTimestamp,
  type FreshnessCadence,
} from "./dataFreshness";
import { usePollingResource } from "./usePollingResource";
import { formatDate, formatInteger, formatNumber } from "./uiFormat";

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
  bemobi_insights?: {
    price_brl?: number | null;
    price_date?: string | null;
    daily_pct?: number | null;
    month_pct?: number | null;
    quarter_pct?: number | null;
    quarter_label?: string | null;
    nav_effect_1m_per_share_nok?: number | null;
    value_per_otec_share_nok?: number | null;
    holding_shares?: number | null;
    ownership_pct?: number | null;
    range_1y?: { low?: number | null; high?: number | null; position_pct?: number | null };
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
    brl_nok?: { date?: string | null; observed_at?: string | null; source?: string | null };
  };
  latest_buyback?: { trade_date?: string; shares?: number } | null;
};

type FreshnessRow = {
  label: string;
  source: string;
  timestamp?: string | null;
  cadence: FreshnessCadence;
};

function readableSource(source?: string | null): string {
  const labels: Record<string, string> = {
    EURONEXT: "Euronext",
    B3: "B3",
    YAHOO_FINANCE: "Yahoo Finance",
    NORGES_BANK: "Norges Bank",
  };
  return source ? labels[source] ?? "—" : "—";
}

function quoteRow(label: string, quote?: Quote): FreshnessRow {
  return {
    label,
    source: readableSource(quote?.source),
    timestamp: quote?.last_updated_at,
    cadence: "intraday",
  };
}

function FreshnessCard({ rows }: { rows: FreshnessRow[] }) {
  return (
    <div className="estimatedHeroSide freshnessCard">
      <span className="label">Datakilder og ferskhet</span>
      <div className="freshnessRows">
        {rows.map((row) => {
          const status = freshnessStatus(row.cadence, row.timestamp);
          return (
            <div className="freshnessRow" key={row.label}>
              <i className={`freshnessDot ${status}`} aria-label={status} />
              <strong>{row.label}</strong>
              <span>{row.source}</span>
              <time>{freshnessTimestamp(row.timestamp)}</time>
            </div>
          );
        })}
      </div>
      <small>Grønn = fersk · Gul = forventet forsinket / marked stengt · Rød = uventet forsinket</small>
    </div>
  );
}

function signed(value: number | null | undefined, digits: number, suffix: string): string {
  if (value == null || !Number.isFinite(value)) return "—";
  const prefix = value > 0 ? "+" : "";
  return `${prefix}${formatNumber(value, digits)}${suffix}`;
}

function tone(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value) || value === 0) return "neutral";
  return value > 0 ? "positive" : "negative";
}

type InsightMetric = {
  label?: string;
  value?: ReactNode;
  valueClassName?: string;
};

function InsightMetricGroup({ metrics }: { metrics: InsightMetric[] }) {
  return (
    <div className="insightMetricGroup">
      {metrics.map((metric, index) => metric.label ? (
        <div className="insightMetricRow" key={metric.label}>
          <span>{metric.label}</span>
          <b className={metric.valueClassName}>{metric.value}</b>
        </div>
      ) : <div className="insightMetricRow insightMetricSlot" key={`empty-${index}`} aria-hidden="true" />)}
    </div>
  );
}

function InsightRange({
  ariaLabel,
  low,
  high,
  position,
}: {
  ariaLabel: string;
  low: string;
  high: string;
  position?: number | null;
}) {
  return (
    <div className="insightRange">
      <span>1 år</span>
      <span>{low}</span>
      <div className="insightRangeTrack" aria-label={ariaLabel}>
        {position != null && Number.isFinite(position) && (
          <i style={{ left: `${Math.max(0, Math.min(100, position))}%` }} />
        )}
      </div>
      <span>{high}</span>
    </div>
  );
}

type EstimatedNav = {
  ready: boolean;
  as_of_date?: string;
  calculated_at?: string | null;
  nav_per_share?: number | null;
  discount_pct?: number | null;
  economic_cash_mnok?: number | null;
  cash_bridge?: {
    report_date?: string | null;
    reported_cash_mnok?: number | null;
    estimated_cash_mnok?: number | null;
    cash_per_share_nok?: number | null;
    change_since_report_mnok?: number | null;
    movements?: Array<{
      key: string;
      label: string;
      amount_mnok?: number | null;
    }>;
  };
};

function cashAmount(value: number | null | undefined, signedValue = false): string {
  if (value == null || !Number.isFinite(value)) return "—";
  const prefix = signedValue && value > 0 ? "+" : "";
  return `${prefix}${formatNumber(value, 1)} mill. kr`;
}

type Forecast = {
  ready: boolean;
  status?: string;
  forecast_week?: { from?: string; to?: string };
  estimate?: { base_case_shares?: number; low_shares?: number; high_shares?: number };
};

type BuybackProgramStatus = {
  forecast?: Forecast;
  program?: {
    cumulative_shares?: number | null;
    vwap_nok?: string | number | null;
    cash_spent_nok?: string | number | null;
    share_count_nav_effect_per_share_nok?: number | null;
  };
  nav_effect?: {
    per_share_nok?: number | null;
    pct?: number | null;
  };
};

function finiteNumber(value: string | number | null | undefined): number | null {
  if (value == null || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function osloDateKey(now = new Date()) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/Oslo",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(now);
  const year = parts.find((part) => part.type === "year")?.value;
  const month = parts.find((part) => part.type === "month")?.value;
  const day = parts.find((part) => part.type === "day")?.value;
  return year && month && day ? `${year}-${month}-${day}` : null;
}

function weekStartKey(input?: string | null) {
  if (!input || !/^\d{4}-\d{2}-\d{2}$/.test(input)) return null;
  const date = new Date(`${input}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return null;
  const weekday = date.getUTCDay() || 7;
  date.setUTCDate(date.getUTCDate() - weekday + 1);
  return date.toISOString().slice(0, 10);
}

function addDaysKey(input: string, days: number) {
  const date = new Date(`${input}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function forecastPeriodLabel(week?: { from?: string; to?: string }) {
  const currentWeek = weekStartKey(osloDateKey());
  const forecastWeek = weekStartKey(week?.from);
  if (!currentWeek || !forecastWeek) return "Kommende uke";
  if (forecastWeek === currentWeek) return "Denne uken";
  if (forecastWeek === addDaysKey(currentWeek, 7)) return "Neste uke";
  return forecastWeek > currentWeek ? "Kommende uke" : "Siste prognose";
}

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
  const { data: nav } = usePollingResource<EstimatedNav>(
    "/api/dashboard/economic",
    REFRESH_MS,
    true,
  );
  const { data: buybackStatus } = usePollingResource<BuybackProgramStatus>(
    "/api/buybacks/dashboard",
    REFRESH_MS,
    true,
  );
  const { data: history } = usePollingResource<DiscountHistory>(
    "/api/dashboard/discount-history?days=365&max_points=72",
    REFRESH_MS,
    true,
  );
  const { data: quotes, refreshFailed: quotesRefreshFailed } =
    usePollingResource<MarketQuotePayload>("/api/market/quotes", REFRESH_MS, true);
  const brlNokDate = summary?.market_timestamps?.brl_nok?.date;
  const cashBridge = nav?.cash_bridge;
  const forecast = buybackStatus?.forecast;
  const buybackProgram = buybackStatus?.program;
  const programVwap = finiteNumber(buybackProgram?.vwap_nok);
  const programCash = finiteNumber(buybackProgram?.cash_spent_nok);
  const buybackNavEffect = buybackStatus?.nav_effect?.per_share_nok;
  const brl = summary?.brl_nok_insights;
  const bemobi = summary?.bemobi_insights;
  const bemobiRange = bemobi?.range_1y;
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
  const hasBemobiRange = bemobiRange?.low != null && bemobiRange?.high != null;
  const brlNokStatus = summaryRefreshFailed
    ? summary
      ? `Viser siste gode kurs ${formatDate(brlNokDate)}`
      : "Kurs utilgjengelig"
    : `Siste kurs ${formatDate(brlNokDate)}`;
  const freshnessRows: FreshnessRow[] = [
    quoteRow("OTEC", quotes?.symbols?.OTEC),
    quoteRow("Bemobi", quotes?.symbols?.BMOB3),
    quoteRow("Life360", quotes?.symbols?.LIF),
    {
      label: "BRL/NOK",
      source: readableSource(summary?.market_timestamps?.brl_nok?.source),
      timestamp: summary?.market_timestamps?.brl_nok?.observed_at
        ?? summary?.market_timestamps?.brl_nok?.date,
      cadence: "daily",
    },
    {
      label: "NAV",
      source: "Beregnet",
      timestamp: nav?.calculated_at,
      cadence: "intraday",
    },
  ];

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
        <FreshnessCard rows={freshnessRows} />
      </section>

      <section className="kpiGrid overviewKpiGrid">
        <article className="card kpi insightCard">
          <span className="label">BRL/NOK</span>
          <div className="insightHeadline">
            <strong>{formatNumber(summary?.brl_nok, 4)}</strong>
            <strong className={tone(brl?.daily_pct)}>{signed(brl?.daily_pct, 2, " %")}</strong>
          </div>
          <small className="insightSubline">{brlNokStatus}</small>
          <div className="insightDivider" />
          <InsightMetricGroup metrics={[
            { label: "1 mnd", value: signed(brl?.month_pct, 1, " %"), valueClassName: tone(brl?.month_pct) },
            { label: brl?.quarter_label ? `Siden ${brl.quarter_label}` : "Siden kvartal", value: signed(brl?.quarter_pct, 1, " %"), valueClassName: tone(brl?.quarter_pct) },
            { label: "NAV-effekt 1 mnd", value: signed(brl?.nav_effect_1m_per_share_nok, 2, " kr/aksje"), valueClassName: tone(brl?.nav_effect_1m_per_share_nok) },
          ]} />
          <InsightMetricGroup metrics={[{}, {}]} />
          <InsightRange ariaLabel="Posisjon i ettårsintervallet" low={hasRange ? formatNumber(range?.low, 2) : "—"} high={hasRange ? formatNumber(range?.high, 2) : "—"} position={range?.position_pct} />
          <small className="insightFootnote" aria-hidden="true">&nbsp;</small>
        </article>
        <article className="card kpi insightCard">
          <span className="label">NAV-rabatt</span>
          <div className="insightHeadline"><strong>{nav?.discount_pct == null ? "—" : `${formatNumber(nav.discount_pct, 1)} %`}</strong></div>
          <small className="insightSubline" aria-hidden="true">&nbsp;</small>
          <div className="insightDivider" />
          <InsightMetricGroup metrics={[
            { label: "NAV / aksje", value: nav?.nav_per_share == null ? "—" : `${formatNumber(nav.nav_per_share, 2)} kr` },
            { label: "Aksjekurs", value: summary?.otec_price == null ? "—" : `${formatNumber(summary.otec_price, 2)} kr` },
            { label: "Oppside til NAV", value: signed(nav?.nav_per_share != null && summary?.otec_price != null ? (nav.nav_per_share / summary.otec_price - 1) * 100 : null, 1, " %"), valueClassName: tone(nav?.nav_per_share != null && summary?.otec_price != null ? (nav.nav_per_share / summary.otec_price - 1) * 100 : null) },
          ]} />
          <InsightMetricGroup metrics={[
            { label: "1 mnd", value: signed(discount?.month_change_pp, 1, " pp"), valueClassName: tone(discount?.month_change_pp == null ? null : -discount.month_change_pp) },
            { label: "1 år median", value: historyStatistics?.median_discount_pct == null ? "—" : `${formatNumber(historyStatistics.median_discount_pct, 1)} %` },
          ]} />
          <InsightRange ariaLabel="Dagens rabatt i ettårsintervallet" low={hasDiscountRange ? `${formatNumber(discountLow, 1)} %` : "—"} high={hasDiscountRange ? `${formatNumber(discountHigh, 1)} %` : "—"} position={discountPosition} />
          <small className="insightFootnote" aria-hidden="true">&nbsp;</small>
        </article>
        <article className="card kpi insightCard">
          <span className="label">Bemobi</span>
          <div className="insightHeadline">
            <strong>{bemobi?.price_brl == null || !Number.isFinite(bemobi.price_brl) ? "—" : `${formatNumber(bemobi.price_brl, 2)} BRL`}</strong>
            <strong className={tone(bemobi?.daily_pct)}>{signed(bemobi?.daily_pct, 1, " %")}</strong>
          </div>
          <small className="insightSubline">Siste kurs {formatDate(bemobi?.price_date)}</small>
          <div className="insightDivider" />
          <InsightMetricGroup metrics={[
            { label: "1 mnd", value: signed(bemobi?.month_pct, 1, " %"), valueClassName: tone(bemobi?.month_pct) },
            { label: bemobi?.quarter_label ? `Siden ${bemobi.quarter_label}` : "Siden kvartal", value: signed(bemobi?.quarter_pct, 1, " %"), valueClassName: tone(bemobi?.quarter_pct) },
            { label: "NAV-effekt 1 mnd", value: signed(bemobi?.nav_effect_1m_per_share_nok, 2, " kr/aksje"), valueClassName: tone(bemobi?.nav_effect_1m_per_share_nok) },
          ]} />
          <InsightMetricGroup metrics={[
            { label: "Verdi / OTEC-aksje", value: bemobi?.value_per_otec_share_nok == null || !Number.isFinite(bemobi.value_per_otec_share_nok) ? "—" : `${formatNumber(bemobi.value_per_otec_share_nok, 2)} kr` },
            { label: "Otello eier", value: bemobi?.holding_shares == null || !Number.isFinite(bemobi.holding_shares) || bemobi?.ownership_pct == null || !Number.isFinite(bemobi.ownership_pct) ? "—" : `${formatNumber(bemobi.holding_shares / 1_000_000, 1)}m / ${formatNumber(bemobi.ownership_pct, 1)} %` },
          ]} />
          <InsightRange ariaLabel="BMOB3-posisjon i ettårsintervallet" low={hasBemobiRange ? formatNumber(bemobiRange?.low, 2) : "—"} high={hasBemobiRange ? formatNumber(bemobiRange?.high, 2) : "—"} position={bemobiRange?.position_pct} />
          <small className="insightFootnote" aria-hidden="true">&nbsp;</small>
        </article>
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
              <span>{forecastPeriodLabel(forecast?.forecast_week)} – baseestimat</span>
              <span className="overviewBuybackValue">
                <strong>{formatInteger(forecast?.estimate?.base_case_shares)} aksjer</strong>
                <small>{formatDate(forecast?.forecast_week?.from)}–{formatDate(forecast?.forecast_week?.to)}</small>
              </span>
            </div>
            <div><span>Estimatintervall</span><strong>{formatInteger(forecast?.estimate?.low_shares)}–{formatInteger(forecast?.estimate?.high_shares)}</strong></div>
            <div><span>Kjøpt siden programstart</span><strong>{buybackProgram?.cumulative_shares == null || !Number.isFinite(buybackProgram.cumulative_shares) ? "—" : `${formatInteger(buybackProgram.cumulative_shares)} aksjer`}</strong></div>
            <div><span>Gjennomsnittlig kjøpskurs</span><strong>{programVwap == null ? "—" : `${formatNumber(programVwap, 2)} kr`}</strong></div>
            <div><span>Kontantbruk hittil</span><strong className="negative">{programCash == null ? "—" : `${formatNumber(programCash / 1_000_000, 1)} mill. kr`}</strong></div>
            <div><span>Netto NAV-effekt fra tilbakekjøp</span><strong className={tone(buybackNavEffect)}>{signed(buybackNavEffect, 2, " kr/aksje")}</strong></div>
          </div>
        </article>

        <article className="card estimatedCashCard">
          <span className="label">Estimert kontantbeholdning</span>
          <strong className="estimatedCashValue">{cashAmount(nav?.economic_cash_mnok)}</strong>
          <strong className="estimatedCashPerShare">
            {cashBridge?.cash_per_share_nok == null || !Number.isFinite(cashBridge.cash_per_share_nok)
              ? "—"
              : `${formatNumber(cashBridge.cash_per_share_nok, 2)} kr / OTEC-aksje`}
          </strong>
          <small className="estimatedCashDate">Estimert per {formatDate(nav?.as_of_date)}</small>
          <div className="cashBridgeRows">
            <div>
              <span>Rapportert kontantbeholdning</span>
              <strong>{cashAmount(cashBridge?.reported_cash_mnok)}</strong>
            </div>
            {(cashBridge?.movements ?? []).map((movement) => (
              <div key={movement.key}>
                <span>{movement.label}</span>
                <strong className={tone(movement.amount_mnok)}>
                  {cashAmount(movement.amount_mnok, true)}
                </strong>
              </div>
            ))}
            <div className="cashBridgeChange">
              <span>Endring siden siste rapport</span>
              <strong className={tone(cashBridge?.change_since_report_mnok)}>
                {cashAmount(cashBridge?.change_since_report_mnok, true)}
              </strong>
            </div>
          </div>
          <small className="estimatedCashFootnote">
            Siste rapporterte kontantbeholdning: {formatDate(cashBridge?.report_date)}
          </small>
        </article>
      </section>

      <MarketQuotePanelWithData data={quotes} failed={quotesRefreshFailed} />
    </div>
  );
}

import { formatDate, formatNumber } from "./uiFormat";
import { usePollingResource } from "./usePollingResource";
import "./market-quote-panel.css";

type Quote = {
  ready: boolean;
  symbol: string;
  currency?: string | null;
  source?: string | null;
  last?: number | null;
  last_updated_at?: string | null;
  trading_date?: string | null;
  changes?: {
    daily_pct?: number | null;
    month_pct?: number | null;
    three_month_pct?: number | null;
  };
  volume?: {
    latest_date?: string | null;
    relative_3m?: number | null;
  };
  range_52w?: { low?: number | null; high?: number | null };
};

type Payload = { ready: boolean; symbols?: Record<string, Quote> };

type Summary = {
  shares_outstanding?: number | null;
  bemobi_value_mnok?: number | null;
  bemobi_insights?: {
    nav_effect_1m_per_share_nok?: number | null;
    value_per_otec_share_nok?: number | null;
    holding_shares?: number | null;
    ownership_pct?: number | null;
  };
};

type EconomicNav = {
  nav_per_share?: number | null;
  discount_pct?: number | null;
  life360?: {
    ready?: boolean;
    market_value_mnok?: number | null;
    nav_effect_1m_per_share_nok?: number | null;
  };
};

type Metric = { label: string; value: string; detail?: string; tone?: string };

const AUTO_REFRESH_MS = 2 * 60 * 1000;
const EMPTY = "—";

function finite(value: number | null | undefined): value is number {
  return value != null && Number.isFinite(value);
}

function price(value: number | null | undefined, currency?: string | null) {
  if (!finite(value)) return EMPTY;
  const formatted = formatNumber(value, 2);
  if (currency === "BRL") return `R$ ${formatted}`;
  if (currency === "NOK") return `${formatted} kr`;
  if (currency === "USD") return `US$ ${formatted}`;
  return formatted;
}

function signed(value: number | null | undefined, digits = 1, suffix = " %") {
  if (!finite(value)) return EMPTY;
  return `${value > 0 ? "+" : ""}${formatNumber(value, digits)}${suffix}`;
}

function tone(value: number | null | undefined) {
  if (!finite(value) || value === 0) return "neutral";
  return value > 0 ? "positive" : "negative";
}

function sourceLabel(source?: string | null) {
  if (source === "EURONEXT") return "Euronext";
  if (source === "YAHOO_FINANCE") return "Yahoo Finance";
  if (source === "B3") return "B3";
  return source ?? EMPTY;
}

function timestamp(value?: string | null) {
  if (!value) return EMPTY;
  const parsed = new Date(value);
  if (!Number.isFinite(parsed.getTime())) return EMPTY;
  return parsed.toLocaleTimeString("nb-NO", { hour: "2-digit", minute: "2-digit" });
}

export function rangePosition(
  current?: number | null,
  low?: number | null,
  high?: number | null,
) {
  if (!finite(current) || !finite(low) || !finite(high) || high < low) return null;
  if (high === low) return 50;
  return Math.max(0, Math.min(100, ((current - low) / (high - low)) * 100));
}

function MarketRange({ quote }: { quote: Quote }) {
  const low = quote.range_52w?.low;
  const high = quote.range_52w?.high;
  const position = rangePosition(quote.last, low, high);
  const available = finite(low) && finite(high) && high >= low;
  return (
    <div className="marketRange">
      <span>52 uker</span>
      <span>{available ? formatNumber(low, 2) : EMPTY}</span>
      <div className="marketRangeTrack" aria-label="Posisjon i 52-ukersintervallet">
        {position != null && <i style={{ left: `${position}%` }} />}
      </div>
      <span>{available ? formatNumber(high, 2) : EMPTY}</span>
    </div>
  );
}

function MetricRows({ metrics }: { metrics: Metric[] }) {
  return <div className="marketMetrics">{metrics.map((metric) => (
    <div className="marketMetricRow" key={metric.label}>
      <span>
        {metric.label}
        {metric.detail && <small>{metric.detail}</small>}
      </span>
      <strong className={metric.tone}>{metric.value}</strong>
    </div>
  ))}</div>;
}

function MarketInsightCard({
  quote,
  title,
  metrics,
  footer,
}: {
  quote?: Quote;
  title: string;
  metrics: Metric[];
  footer: string;
}) {
  if (!quote?.ready) {
    return <article className="card marketQuoteCard marketQuoteUnavailable">
      <span className="label">{title}</span><strong>Kursdata mangler</strong>
    </article>;
  }
  const source = sourceLabel(quote.source);
  return (
    <article className="card marketQuoteCard">
      <span className="label">{title}</span>
      <div className="marketQuoteHeadline">
        <strong>{price(quote.last, quote.currency)}</strong>
        <strong className={tone(quote.changes?.daily_pct)}>
          {signed(quote.changes?.daily_pct)}
        </strong>
      </div>
      <small className="marketQuoteSubline">
        {formatDate(quote.trading_date)} · {source} · {timestamp(quote.last_updated_at)}
      </small>
      <div className="marketDivider" />
      <MetricRows metrics={metrics} />
      <div className="marketDivider" />
      <MetricRows metrics={[
        { label: "1 mnd", value: signed(quote.changes?.month_pct), tone: tone(quote.changes?.month_pct) },
        { label: "3 mnd", value: signed(quote.changes?.three_month_pct), tone: tone(quote.changes?.three_month_pct) },
      ]} />
      <MarketRange quote={quote} />
      <small className="marketQuoteFooter">{footer}</small>
    </article>
  );
}

export default function MarketQuotePanel() {
  const { data, refreshFailed: failed } = usePollingResource<Payload>(
    "/api/market/quotes",
    AUTO_REFRESH_MS,
    true,
  );
  const { data: summary } = usePollingResource<Summary>(
    "/api/dashboard/summary",
    AUTO_REFRESH_MS,
    true,
  );
  const { data: nav } = usePollingResource<EconomicNav>(
    "/api/dashboard/economic",
    AUTO_REFRESH_MS,
    true,
  );
  const bemobi = summary?.bemobi_insights;
  const lifeValue = nav?.life360?.ready ? nav.life360.market_value_mnok : null;
  const lifePerShare = finite(lifeValue) && finite(summary?.shares_outstanding) && summary.shares_outstanding > 0
    ? lifeValue * 1_000_000 / summary.shares_outstanding
    : null;

  return (
    <section className="marketQuoteSection">
      <div className="marketQuoteSectionHeader">
        <div><span className="label">Markedsdata</span><h2>Kurser og handelsdata</h2></div>
        {failed && <span className="pill muted">Viser sist hentet</span>}
      </div>
      <div className="marketQuoteGrid">
        <MarketInsightCard quote={data?.symbols?.OTEC} title="OTEC" footer="Kilde: Euronext · 30 min refresh" metrics={[
          { label: "NAV / aksje", value: finite(nav?.nav_per_share) ? `${formatNumber(nav.nav_per_share, 2)} kr` : EMPTY },
          { label: "NAV-rabatt", value: finite(nav?.discount_pct) ? `${formatNumber(nav.discount_pct, 1)} %` : EMPTY },
          {
            label: "Siste dagsvolum vs 3 mnd snitt",
            value: finite(data?.symbols?.OTEC?.volume?.relative_3m)
              ? `${formatNumber(data.symbols.OTEC.volume.relative_3m, 1)}×`
              : EMPTY,
            detail: data?.symbols?.OTEC?.volume?.latest_date
              ? formatDate(data.symbols.OTEC.volume.latest_date)
              : undefined,
          },
        ]} />
        <MarketInsightCard quote={data?.symbols?.BMOB3} title="Bemobi / BMOB3" footer="Kilde: B3 · 30 min refresh" metrics={[
          { label: "Verdi for Otello", value: finite(summary?.bemobi_value_mnok) ? `${formatNumber(summary.bemobi_value_mnok, 1)} mill. kr` : EMPTY },
          { label: "Verdi / OTEC-aksje", value: finite(bemobi?.value_per_otec_share_nok) ? `${formatNumber(bemobi.value_per_otec_share_nok, 2)} kr` : EMPTY },
          { label: "NAV-effekt 1 mnd", value: signed(bemobi?.nav_effect_1m_per_share_nok, 2, " kr/aksje"), tone: tone(bemobi?.nav_effect_1m_per_share_nok) },
        ]} />
        <MarketInsightCard quote={data?.symbols?.LIF} title="Life360 / LIF" footer="Kilde: Yahoo Finance · 30 min refresh" metrics={[
          { label: "Verdi for Otello", value: finite(lifeValue) ? `${formatNumber(lifeValue, 1)} mill. kr` : EMPTY },
          { label: "Verdi / OTEC-aksje", value: finite(lifePerShare) ? `${formatNumber(lifePerShare, 2)} kr` : EMPTY },
          { label: "NAV-effekt 1 mnd", value: signed(nav?.life360?.nav_effect_1m_per_share_nok, 2, " kr/aksje"), tone: tone(nav?.life360?.nav_effect_1m_per_share_nok) },
        ]} />
      </div>
    </section>
  );
}

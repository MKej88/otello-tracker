import type { MarketQuotePayload, Quote } from "./MarketQuotePanel";
import { usePollingResource } from "./usePollingResource";
import { formatDate, formatInteger, formatNumber } from "./uiFormat";
import "./overview-page.css";

const REFRESH_MS = 2 * 60 * 1000;
const EVENT_REFRESH_MS = 5 * 60 * 1000;

type Summary = {
  ready: boolean;
  otec_price?: number | null;
  brl_nok?: number | null;
  brl_nok_insights?: {
    daily_pct?: number | null;
    month_pct?: number | null;
    nav_effect_1m_per_share_nok?: number | null;
  };
  bemobi_insights?: {
    price_brl?: number | null;
    daily_pct?: number | null;
    month_pct?: number | null;
    nav_effect_1m_per_share_nok?: number | null;
  };
};

type EstimatedNav = {
  ready: boolean;
  as_of_date?: string;
  calculated_at?: string | null;
  nav_per_share?: number | null;
  discount_pct?: number | null;
  economic_cash_mnok?: number | null;
  cash_bridge?: {
    report_date?: string | null;
    cash_per_share_nok?: number | null;
    change_since_report_mnok?: number | null;
  };
};

type BuybackProgramStatus = {
  program?: {
    cumulative_shares?: number | null;
    progress_pct?: number | null;
    vwap_nok?: string | number | null;
  };
  nav_effect?: {
    per_share_nok?: number | null;
  };
};

type DiscountHistory = {
  estimated?: {
    ready: boolean;
    statistics?: {
      median_discount_pct?: number | null;
    };
  };
};

type NewsEvent = {
  id: string | number;
  date: string;
  company: "Otello" | "Bemobi";
  title: string;
  importance: "HIGH" | "MEDIUM" | "LOW";
  confirmed: boolean;
  source?: string | null;
};

type NewsEventsPayload = {
  ready: boolean;
  events?: NewsEvent[];
};

type BrazilCalendarEvent = {
  date: string;
  name: string;
  kind: string;
  importance: string;
};

type BrazilCalendarPayload = {
  calendar?: BrazilCalendarEvent[];
};

type OverviewEvent = {
  id: string;
  date: string;
  title: string;
  badge: string;
  badgeClass: "bemobi" | "otello" | "macro";
  confirmed: boolean;
  source?: string | null;
  importance: number;
};

function finiteNumber(value: string | number | null | undefined): number | null {
  if (value == null || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function signed(value: number | null | undefined, digits: number, suffix: string): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${value > 0 ? "+" : ""}${formatNumber(value, digits)}${suffix}`;
}

function tone(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value) || value === 0) return "neutral";
  return value > 0 ? "positive" : "negative";
}

function updatedTimeLabel(value?: string | null) {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "—";
  return parsed.toLocaleTimeString("nb-NO", {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Europe/Oslo",
  });
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

function eventDateLabel(input: string) {
  const date = new Date(`${input}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return formatDate(input);
  return new Intl.DateTimeFormat("nb-NO", {
    day: "2-digit",
    month: "short",
    timeZone: "UTC",
  }).format(date).replace(".", "");
}

function daysUntil(input: string) {
  const today = osloDateKey();
  if (!today) return null;
  const current = new Date(`${today}T00:00:00Z`).getTime();
  const target = new Date(`${input}T00:00:00Z`).getTime();
  if (!Number.isFinite(current) || !Number.isFinite(target)) return null;
  return Math.round((target - current) / 86_400_000);
}

function countdownLabel(input: string) {
  const days = daysUntil(input);
  if (days == null) return "";
  if (days === 0) return "I dag";
  if (days === 1) return "I morgen";
  return days > 1 ? `Om ${days} dager` : "";
}

function macroTitle(event: BrazilCalendarEvent) {
  const labels: Record<string, string> = {
    copom: "Rentebeslutning fra sentralbanken",
    services: "Aktivitet i tjenestenæringene",
    retail: "Omsetning i detaljhandelen",
    activity: "Samlet økonomisk aktivitet",
    labor: "Arbeidsledighet",
  };
  if (event.kind === "inflation") return event.name.includes("15") ? "Foreløpig prisvekst" : "Prisvekst";
  if (event.kind === "gdp") return event.name.replace("BNP", "Økonomisk vekst (BNP)");
  return labels[event.kind] ?? event.name;
}

function upcomingEvents(
  companyPayload?: NewsEventsPayload | null,
  brazilPayload?: BrazilCalendarPayload | null,
): OverviewEvent[] {
  const today = osloDateKey();
  if (!today) return [];
  const events: OverviewEvent[] = [];

  for (const event of companyPayload?.events ?? []) {
    if (!event.date || event.date < today) continue;
    events.push({
      id: `company-${event.id}`,
      date: event.date,
      title: event.title,
      badge: event.company,
      badgeClass: event.company === "Bemobi" ? "bemobi" : "otello",
      confirmed: event.confirmed,
      source: event.source,
      importance: event.importance === "HIGH" ? 0 : event.importance === "MEDIUM" ? 1 : 2,
    });
  }

  for (const event of brazilPayload?.calendar ?? []) {
    if (!event.date || event.date < today || !event.importance.startsWith("Høy")) continue;
    events.push({
      id: `macro-${event.date}-${event.kind}-${event.name}`,
      date: event.date,
      title: macroTitle(event),
      badge: "Makro",
      badgeClass: "macro",
      confirmed: true,
      source: "BCB / IBGE",
      importance: 0,
    });
  }

  return events
    .sort((left, right) => left.date.localeCompare(right.date) || left.importance - right.importance || left.title.localeCompare(right.title))
    .slice(0, 4);
}

function quotePrice(quote?: Quote) {
  if (quote?.last == null || !Number.isFinite(quote.last)) return "—";
  if (quote.currency === "BRL") return `R$${formatNumber(quote.last, 2)}`;
  if (quote.currency === "USD") return `$${formatNumber(quote.last, 2)}`;
  if (quote.currency === "NOK") return `${formatNumber(quote.last, 2)} kr`;
  return formatNumber(quote.last, 2);
}

function MarketTicker({ label, quote }: { label: string; quote?: Quote }) {
  return (
    <div className="overviewTickerItem">
      <span>{label}</span>
      <strong>{quotePrice(quote)}</strong>
      <b className={tone(quote?.changes?.daily_pct)}>{signed(quote?.changes?.daily_pct, 1, " %")}</b>
    </div>
  );
}

export default function OverviewPage() {
  const { data: summary } = usePollingResource<Summary>(
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
  const { data: quotes, refreshFailed: quotesRefreshFailed } = usePollingResource<MarketQuotePayload>(
    "/api/market/quotes",
    REFRESH_MS,
    true,
  );
  const { data: newsEvents } = usePollingResource<NewsEventsPayload>(
    "/api/news-events",
    EVENT_REFRESH_MS,
    true,
  );
  const { data: brazilCalendar } = usePollingResource<BrazilCalendarPayload>(
    "/api/brazil/dashboard",
    EVENT_REFRESH_MS,
    true,
  );

  const brl = summary?.brl_nok_insights;
  const bemobi = summary?.bemobi_insights;
  const buybackProgram = buybackStatus?.program;
  const buybackNavEffect = buybackStatus?.nav_effect?.per_share_nok;
  const programVwap = finiteNumber(buybackProgram?.vwap_nok);
  const cashBridge = nav?.cash_bridge;
  const discountMedian = history?.estimated?.statistics?.median_discount_pct;
  const discountSpread = nav?.discount_pct != null && discountMedian != null
    ? nav.discount_pct - discountMedian
    : null;
  const events = upcomingEvents(newsEvents, brazilCalendar);
  const nextEvent = events[0];
  const otecVolumeRelative = quotes?.symbols?.OTEC?.volume?.relative_3m;

  return (
    <div className="investorPage overviewV3">
      <section className="overviewHeroGrid">
        <article className="card overviewNavCard overviewNavCardV3">
          <span className="label">NAV</span>
          <h2>{nav?.ready ? `${formatNumber(nav.nav_per_share, 2)} kr` : "Laster …"}</h2>
          <div className="overviewNavSnapshot">
            <div><span>OTEC</span><strong>{summary?.otec_price == null ? "—" : `${formatNumber(summary.otec_price, 2)} kr`}</strong></div>
            <div><span>Rabatt</span><strong>{nav?.discount_pct == null ? "—" : `${formatNumber(nav.discount_pct, 1)} %`}</strong></div>
            <div><span>1 års median</span><strong>{discountMedian == null ? "—" : `${formatNumber(discountMedian, 1)} %`}</strong></div>
          </div>
          <div className="overviewDiscountContext">
            {discountSpread == null
              ? "Historisk rabatt sammenlignes når data er tilgjengelige."
              : discountSpread >= 0
                ? `Rabatten er ${formatNumber(discountSpread, 1)} pp bredere enn 1-årsmedianen.`
                : `Rabatten er ${formatNumber(Math.abs(discountSpread), 1)} pp smalere enn 1-årsmedianen.`}
          </div>
          <small className="overviewUpdated">NAV oppdatert {updatedTimeLabel(nav?.calculated_at)}</small>
        </article>

        <article className="card overviewUpcomingCard overviewUpcomingCardV3">
          <div className="overviewUpcomingHeader">
            <div><span className="label">NESTE VIKTIGE DATOER</span><h2>Hva bør følges nå?</h2></div>
          </div>
          {nextEvent ? (
            <>
              <div className="overviewNextEvent">
                <div className="overviewNextEventDate">
                  <strong>{eventDateLabel(nextEvent.date)}</strong>
                  <span>{countdownLabel(nextEvent.date)}</span>
                </div>
                <div className="overviewNextEventMain">
                  <div>
                    <strong>{nextEvent.title}</strong>
                    <span className={`overviewEventBadge ${nextEvent.badgeClass}`}>{nextEvent.badge}</span>
                  </div>
                  <small>{nextEvent.confirmed ? "Bekreftet dato" : "Forventet dato"}{nextEvent.source ? ` · ${nextEvent.source}` : ""}</small>
                </div>
              </div>
              {events.length > 1 && (
                <div className="overviewUpcomingRows">
                  {events.slice(1).map((event) => (
                    <div key={event.id}>
                      <time>{eventDateLabel(event.date)}</time>
                      <strong>{event.title}</strong>
                      <span className={`overviewEventBadge ${event.badgeClass}`}>{event.badge}</span>
                    </div>
                  ))}
                </div>
              )}
            </>
          ) : (
            <div className="overviewUpcomingEmpty">Ingen kommende selskaps- eller makrohendelser med høy relevans er registrert.</div>
          )}
        </article>
      </section>

      <section className="overviewSection">
        <div className="overviewSectionHeading">
          <div><span className="label">HVA DRIVER NAV NÅ?</span><h2>De viktigste verdidriverne</h2></div>
          <small>Siste måned for markedsdriverne · akkumulert effekt for tilbakekjøp.</small>
        </div>
        <div className="overviewDriverGrid">
          <article className="card overviewDriverCard">
            <span className="label">BEMOBI</span>
            <strong>{signed(bemobi?.month_pct, 1, " % siste måned")}</strong>
            <div className={`overviewDriverEffect ${tone(bemobi?.nav_effect_1m_per_share_nok)}`}>
              {signed(bemobi?.nav_effect_1m_per_share_nok, 2, " kr NAV/aksje")}
            </div>
            <small>BMOB3 {bemobi?.price_brl == null ? "—" : `R$${formatNumber(bemobi.price_brl, 2)}`}</small>
          </article>

          <article className="card overviewDriverCard">
            <span className="label">BRL/NOK</span>
            <strong>{signed(brl?.month_pct, 1, " % siste måned")}</strong>
            <div className={`overviewDriverEffect ${tone(brl?.nav_effect_1m_per_share_nok)}`}>
              {signed(brl?.nav_effect_1m_per_share_nok, 2, " kr NAV/aksje")}
            </div>
            <small>Dagens kurs {summary?.brl_nok == null ? "—" : formatNumber(summary.brl_nok, 4)}</small>
          </article>

          <article className="card overviewDriverCard">
            <span className="label">TILBAKEKJØP</span>
            <strong>{buybackProgram?.cumulative_shares == null ? "—" : `${formatInteger(buybackProgram.cumulative_shares)} aksjer kjøpt`}</strong>
            <div className={`overviewDriverEffect ${tone(buybackNavEffect)}`}>
              {signed(buybackNavEffect, 2, " kr netto NAV/aksje")}
            </div>
            <small>{buybackProgram?.progress_pct == null ? "—" : `${formatNumber(buybackProgram.progress_pct, 1)} % av programmet gjennomført`}</small>
          </article>
        </div>
      </section>

      <section className="overviewSection">
        <div className="overviewSectionHeading">
          <div><span className="label">KAPITAL</span><h2>Cash og tilbakekjøp</h2></div>
        </div>
        <div className="overviewCapitalGrid">
          <article className="card overviewCapitalCard">
            <span className="label">CASH</span>
            <strong className="overviewCapitalValue">{nav?.economic_cash_mnok == null ? "—" : `${formatNumber(nav.economic_cash_mnok, 1)} mill. kr`}</strong>
            <span>{cashBridge?.cash_per_share_nok == null ? "—" : `${formatNumber(cashBridge.cash_per_share_nok, 2)} kr / OTEC-aksje`}</span>
            <div className="overviewCapitalMeta">
              <span>Endring siden siste rapport</span>
              <strong className={tone(cashBridge?.change_since_report_mnok)}>{signed(cashBridge?.change_since_report_mnok, 1, " mill. kr")}</strong>
            </div>
            <a className="overviewDeepLink" href="#cash">Se cash og kapitalallokering →</a>
          </article>

          <article className="card overviewCapitalCard">
            <span className="label">TILBAKEKJØP</span>
            <strong className="overviewCapitalValue">{buybackProgram?.progress_pct == null ? "—" : `${formatNumber(buybackProgram.progress_pct, 1)} % gjennomført`}</strong>
            <span>{buybackProgram?.cumulative_shares == null ? "—" : `${formatInteger(buybackProgram.cumulative_shares)} aksjer kjøpt`}</span>
            <div className="overviewCapitalMeta overviewCapitalMetaTwo">
              <div><span>Snittpris</span><strong>{programVwap == null ? "—" : `${formatNumber(programVwap, 2)} kr`}</strong></div>
              <div><span>Netto NAV-effekt</span><strong className={tone(buybackNavEffect)}>{signed(buybackNavEffect, 2, " kr/aksje")}</strong></div>
            </div>
            <a className="overviewDeepLink" href="#tilbakekjop">Se tilbakekjøpsprogram →</a>
          </article>
        </div>
      </section>

      <section className="card overviewMarketStrip">
        <div className="overviewMarketStripHeader">
          <span className="label">MARKED</span>
          {quotesRefreshFailed ? <small>Viser siste gode markedsdata</small> : null}
        </div>
        <div className="overviewTickerGrid">
          <MarketTicker label="OTEC" quote={quotes?.symbols?.OTEC} />
          <MarketTicker label="BMOB3" quote={quotes?.symbols?.BMOB3} />
          <div className="overviewTickerItem">
            <span>BRL/NOK</span>
            <strong>{summary?.brl_nok == null ? "—" : formatNumber(summary.brl_nok, 4)}</strong>
            <b className={tone(brl?.daily_pct)}>{signed(brl?.daily_pct, 1, " %")}</b>
          </div>
          <MarketTicker label="LIF" quote={quotes?.symbols?.LIF} />
        </div>
        {otecVolumeRelative != null && Number.isFinite(otecVolumeRelative) && otecVolumeRelative >= 1.5 ? (
          <small className="overviewVolumeAlert">OTEC-volum siste handelsdag: {formatNumber(otecVolumeRelative, 1)}× 3-månederssnitt.</small>
        ) : null}
      </section>
    </div>
  );
}

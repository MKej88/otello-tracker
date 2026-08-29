import MarketQuotePanel from "./MarketQuotePanel";
import { usePollingResource } from "./usePollingResource";
import { formatDate, formatDateTime, formatInteger, formatNumber } from "./uiFormat";

const REFRESH_MS = 2 * 60 * 1000;

type Summary = {
  ready: boolean;
  as_of_date?: string;
  otec_price?: number | null;
  brl_nok?: number | null;
  bemobi_value_mnok?: number | null;
  bemobi_ownership_pct?: number | null;
  market_timestamps?: {
    brl_nok?: { date?: string | null };
  };
  latest_buyback?: { trade_date?: string; shares?: number } | null;
};

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

export default function OverviewPage() {
  const { data: summary, refreshFailed: summaryRefreshFailed } = usePollingResource<Summary>("/api/dashboard/summary", REFRESH_MS);
  const { data: nav, refreshFailed } = usePollingResource<EstimatedNav>("/api/dashboard/economic", REFRESH_MS);
  const { data: forecast } = usePollingResource<Forecast>("/api/buybacks/forecast", REFRESH_MS);
  const brlNokDate = summary?.market_timestamps?.brl_nok?.date;

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
        <article className="card kpi">
          <span className="label">BRL/NOK</span>
          <strong>{formatNumber(summary?.brl_nok, 4)}</strong>
          <small>{summaryRefreshFailed ? "Viser siste gode kurs" : "Siste kurs"} {formatDate(brlNokDate)}</small>
        </article>
        <article className="card kpi"><span className="label">NAV-rabatt</span><strong>{formatNumber(nav?.discount_pct, 1)} %</strong></article>
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

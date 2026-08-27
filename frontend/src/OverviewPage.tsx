import MarketQuotePanel from "./MarketQuotePanel";
import { usePollingResource } from "./usePollingResource";

const REFRESH_MS = 2 * 60 * 1000;

type Summary = {
  ready: boolean;
  as_of_date?: string;
  otec_price?: number | null;
  bemobi_value_mnok?: number | null;
  bemobi_ownership_pct?: number | null;
  latest_buyback?: { trade_date?: string; shares?: number } | null;
};

type EstimatedNav = {
  ready: boolean;
  as_of_date?: string;
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

function value(input?: number | null, digits = 2) {
  if (input == null || !Number.isFinite(input)) return "–";
  return input.toLocaleString("nb-NO", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function integer(input?: number | null) {
  if (input == null || !Number.isFinite(input)) return "–";
  return Math.round(input).toLocaleString("nb-NO");
}

function dateLabel(input?: string | null) {
  if (!input) return "–";
  const [year, month, day] = input.slice(0, 10).split("-");
  return year && month && day ? `${day}.${month}.${year}` : input;
}

export default function OverviewPage() {
  const { data: summary } = usePollingResource<Summary>("/api/dashboard/summary", REFRESH_MS);
  const { data: nav, refreshFailed } = usePollingResource<EstimatedNav>("/api/dashboard/economic", REFRESH_MS);
  const { data: forecast } = usePollingResource<Forecast>("/api/buybacks/forecast", REFRESH_MS);

  return (
    <div className="investorPage overviewV2">
      <section className="estimatedHero card">
        <div>
          <span className="label">ESTIMERT NAV</span>
          <h2>{nav?.ready ? `${value(nav.nav_per_share)} kr` : "Laster …"}</h2>
          <p>
            Dagens beste estimat på verdien per Otello-aksje basert på markedsverdier,
            valuta, kontantbeholdning, drift og opsjonsoppgjør.
          </p>
        </div>
        <div className="estimatedHeroSide">
          <div><span>OTEC</span><strong>{value(summary?.otec_price)} kr</strong></div>
          <div><span>Rabatt til Estimert NAV</span><strong>{value(nav?.discount_pct, 1)} %</strong></div>
          <small>Datadato {dateLabel(nav?.as_of_date ?? summary?.as_of_date)}</small>
          {refreshFailed && <small>Viser siste gode data</small>}
        </div>
      </section>

      <section className="kpiGrid overviewKpiGrid">
        <article className="card kpi"><span className="label">OTEC-kurs</span><strong>{value(summary?.otec_price)} kr</strong></article>
        <article className="card kpi"><span className="label">Estimert NAV</span><strong>{value(nav?.nav_per_share)} kr</strong></article>
        <article className="card kpi"><span className="label">NAV-rabatt</span><strong>{value(nav?.discount_pct, 1)} %</strong></article>
        <article className="card kpi"><span className="label">Bemobi-verdi</span><strong>{value(summary?.bemobi_value_mnok, 1)} mill. kr</strong></article>
      </section>

      <section className="overviewGrid">
        <article className="card">
          <div className="cardHeader"><div><span className="label">Kapitalallokering</span><h2>Tilbakekjøpsprogram</h2></div></div>
          <div className="placeholderRows">
            <div><span>Siste rapporterte kjøp</span><strong>{integer(summary?.latest_buyback?.shares)} aksjer</strong><small>{dateLabel(summary?.latest_buyback?.trade_date)}</small></div>
            <div><span>Neste uke – baseestimat</span><strong>{integer(forecast?.estimate?.base_case_shares)} aksjer</strong><small>{dateLabel(forecast?.forecast_week?.from)}–{dateLabel(forecast?.forecast_week?.to)}</small></div>
            <div><span>Estimatintervall</span><strong>{integer(forecast?.estimate?.low_shares)}–{integer(forecast?.estimate?.high_shares)}</strong></div>
          </div>
        </article>

        <article className="card">
          <div className="cardHeader"><div><span className="label">Underliggende verdi</span><h2>Bemobi</h2></div></div>
          <div className="placeholderRows">
            <div><span>Verdi for Otello</span><strong>{value(summary?.bemobi_value_mnok, 1)} mill. kr</strong></div>
            <div><span>Otellos eierandel</span><strong>{value(summary?.bemobi_ownership_pct, 1)} %</strong></div>
            <div><span>Estimert kontantbeholdning</span><strong>{value(nav?.economic_cash_mnok, 1)} mill. kr</strong></div>
          </div>
        </article>
      </section>

      <MarketQuotePanel />
    </div>
  );
}

import MarketQuotePanel from "./MarketQuotePanel";
import { usePollingResource } from "./usePollingResource";
import "./economic-nav.css";

type EconomicNav = {
  ready: boolean;
  reason?: string;
  as_of_date?: string;
  quality?: string;
  accounting_nav_per_share?: number | null;
  nav_per_share?: number | null;
  discount_pct?: number | null;
  conservative_nav_per_share?: number | null;
  conservative_discount_pct?: number | null;
  economic_cash_mnok?: number | null;
  cash_fx?: {
    quality?: string;
    allocation_quality?: string;
    adjustment_mnok?: number | null;
    coverage_pct?: number | null;
    anchor_date?: string;
  };
  life360?: {
    ready?: boolean;
    reason?: string;
    shares?: number;
    holding_basis?: string;
    history_available_from?: string;
    market_symbol?: string;
    currency?: string;
    price?: number | null;
    price_date?: string;
    price_age_days?: number;
    price_source?: string;
    fx_rate?: number | null;
    fx_date?: string;
    market_value_mnok?: number | null;
    embedded_value_mnok?: number | null;
    adjustment_mnok?: number | null;
    anchor_date?: string;
    anchor_price_usd?: number | null;
    stale?: boolean;
  };
  option?: {
    accounting_liability_mnok?: number | null;
    economic_value_mnok?: number | null;
    black_scholes_gross_mnok?: number | null;
    settlement_mnok?: number | null;
    conservative_settlement_mnok?: number | null;
    settlement_per_option_nok?: number | null;
    option_count?: number | null;
    strike_nok?: number | null;
    nav_before_option_per_share_nok?: number | null;
    nav_after_option_per_share_nok?: number | null;
    method?: string;
    full_realisation_scenario?: boolean;
  };
  operating_costs?: {
    anchor_date?: string;
    days_since_anchor?: number;
    base_mnok?: number | null;
    conservative_mnok?: number | null;
    base_annualized_usd_m?: number | null;
    conservative_annualized_usd_m?: number | null;
    source_period?: string;
    interest_income_included?: boolean;
  };
};

type Props = {
  variant?: "summary" | "detail";
};

const AUTO_REFRESH_MS = 2 * 60 * 1000;

function value(input: number | null | undefined, digits = 2) {
  if (input == null || !Number.isFinite(input)) return "–";
  return input.toLocaleString("nb-NO", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits
  });
}

function integer(input: number | null | undefined) {
  if (input == null || !Number.isFinite(input)) return "–";
  return Math.round(input).toLocaleString("nb-NO");
}

function signedValue(input: number | null | undefined, digits = 1) {
  if (input == null || !Number.isFinite(input)) return "–";
  const prefix = input > 0 ? "+" : "";
  return `${prefix}${value(input, digits)} mill.`;
}

function dateLabel(input?: string | null) {
  if (!input) return "–";
  const [year, month, day] = input.split("-");
  if (!year || !month || !day) return input;
  return `${day}.${month}.${year}`;
}

function reasonLabel(reason?: string) {
  if (reason === "api_error") return "API-feil";
  if (reason === "missing_option_settlement_inputs") return "Mangler grunnlag for opsjonsoppgjør";
  return "Ikke klart";
}

export default function EconomicNavPanel({ variant = "summary" }: Props) {
  const { data, refreshFailed } = usePollingResource<EconomicNav>(
    "/api/dashboard/economic",
    AUTO_REFRESH_MS
  );

  if (data == null) {
    if (!refreshFailed) return variant === "summary" ? <MarketQuotePanel /> : null;
    return (
      <section className="economicNavHost">
        <div className="economicNavPanel economicNavUnavailable">
          <div>
            <span className="economicEyebrow">Investorjustert NAV</span>
            <strong>Økonomisk NAV kunne ikke hentes</strong>
          </div>
          <span>{reasonLabel("api_error")}</span>
        </div>
        {variant === "summary" && <MarketQuotePanel />}
      </section>
    );
  }

  if (!data.ready) {
    return (
      <section className="economicNavHost">
        <div className="economicNavPanel economicNavUnavailable">
          <div>
            <span className="economicEyebrow">Investorjustert NAV</span>
            <strong>Økonomisk NAV venter på komplett FULL NAV-grunnlag</strong>
          </div>
          <span>{reasonLabel(data.reason)}</span>
        </div>
        {variant === "summary" && <MarketQuotePanel />}
      </section>
    );
  }

  const option = data.option;
  const costs = data.operating_costs;
  const cashFx = data.cash_fx;
  const life360 = data.life360;

  return (
    <section className="economicNavHost">
      <article className="economicNavPanel">
        <div className="economicHeader">
          <div>
            <span className="economicEyebrow">Investorjustert verdsettelse</span>
            <h2>Økonomisk NAV</h2>
          </div>
          <span className="economicBadge">
            {refreshFailed ? "SISTE GODE DATA" : "ESTIMERT MELLOM RAPPORTER"}
          </span>
        </div>

        <div className="economicMetrics">
          <div>
            <span>Regnskapsmessig FULL NAV</span>
            <strong>{value(data.accounting_nav_per_share)} kr</strong>
          </div>
          <div className="economicPrimary">
            <span>Økonomisk NAV</span>
            <strong>{value(data.nav_per_share)} kr</strong>
            <small>Rabatt {value(data.discount_pct, 1)} %</small>
          </div>
          <div>
            <span>Konservativ NAV</span>
            <strong>{value(data.conservative_nav_per_share)} kr</strong>
            <small>Rabatt {value(data.conservative_discount_pct, 1)} %</small>
          </div>
          <div>
            <span>Økonomisk kontantbeholdning</span>
            <strong>{value(data.economic_cash_mnok, 1)} mill. kr</strong>
            <small>etter valuta og drift, før hypotetisk opsjonsoppgjør</small>
          </div>
        </div>

        {variant === "detail" && (
          <>
            <div className="economicAdjustments">
              <div>
                <span>Valutaeffekt på cash</span>
                <strong>{signedValue(cashFx?.adjustment_mnok)}</strong>
                <small>
                  {cashFx?.coverage_pct != null
                    ? `${value(cashFx.coverage_pct, 1)} % av rapportankeret valutafordelt`
                    : "–"}
                </small>
              </div>
              <div>
                <span>Life360 – mark-to-market</span>
                <strong>{life360?.ready ? signedValue(life360.adjustment_mnok) : "–"}</strong>
                <small>
                  {life360?.ready
                    ? `${integer(life360.shares)} LIF · USD ${value(life360.price, 2)} · verdi ${value(life360.market_value_mnok, 1)} mill. kr · kurs ${dateLabel(life360.price_date)}`
                    : "Venter på gyldig LIF-kurs og rapportanker"}
                </small>
              </div>
              <div>
                <span>Opsjoner – kontantoppgjør ved NAV</span>
                <strong>−{value(option?.settlement_mnok, 1)} mill.</strong>
                <small>
                  {integer(option?.option_count)} opsjoner · strike {value(option?.strike_nok, 2)} kr · NAV før opsjon {value(option?.nav_before_option_per_share_nok, 2)} kr
                </small>
              </div>
              <div>
                <span>Estimert drift siden {dateLabel(costs?.anchor_date)}</span>
                <strong>−{value(costs?.base_mnok, 1)} mill.</strong>
              </div>
            </div>

            <div className="economicFootnote">
              <span>
                Life360-linjen erstatter markedsverdien som allerede ligger i siste rapporterte «andre investeringer»-anker; den legges ikke oppå hele posten. Historiske Life360-markedsdata lagres fra ASX-noteringen i 2019, mens investor-NAV bruker Nasdaq LIF fra fair-value-perioden.
              </span>
              <span>
                Opsjonslinjen er et scenario ved full Bemobi-realisering: OTEC-kurs ved exercise settes lik NAV etter kontantoppgjøret. Regnskapsført Black–Scholes-verdi beholdes kun som kontrollgrunnlag i modellen.
              </span>
              <span>
                Årlig driftskostnadsnivå: ca. USD {value(costs?.base_annualized_usd_m, 2)} mill.
                {costs?.source_period ? ` (${costs.source_period})` : ""}. Renteinntekter er ikke lagt til. Data {dateLabel(data.as_of_date)}.
              </span>
            </div>
          </>
        )}
      </article>
      {variant === "summary" && <MarketQuotePanel />}
    </section>
  );
}
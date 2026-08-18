import { useEffect, useState } from "react";
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
    adjustment_mnok?: number | null;
    coverage_pct?: number | null;
    anchor_date?: string;
  };
  option?: {
    accounting_liability_mnok?: number | null;
    economic_value_mnok?: number | null;
    unrecognized_overhang_mnok?: number | null;
  };
  operating_costs?: {
    anchor_date?: string;
    days_since_anchor?: number;
    base_mnok?: number | null;
    conservative_mnok?: number | null;
    base_annualized_usd_m?: number | null;
    conservative_annualized_usd_m?: number | null;
    usd_nok?: number | null;
    usd_nok_date?: string;
    source_period?: string;
    interest_income_included?: boolean;
  };
  note?: string;
};

const AUTO_REFRESH_MS = 2 * 60 * 1000;

function value(input: number | null | undefined, digits = 2) {
  if (input == null || !Number.isFinite(input)) return "–";
  return input.toLocaleString("nb-NO", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits
  });
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
  return "Ikke klart";
}

export default function EconomicNavPanel() {
  const [data, setData] = useState<EconomicNav | null>(null);

  useEffect(() => {
    let active = true;

    const load = () => {
      fetch("/api/dashboard/economic")
        .then((response) => {
          if (!response.ok) throw new Error("Economic NAV API-feil");
          return response.json() as Promise<EconomicNav>;
        })
        .then((result) => {
          if (active) setData(result);
        })
        .catch(() => {
          if (active) setData({ ready: false, reason: "api_error" });
        });
    };

    load();
    const timer = window.setInterval(load, AUTO_REFRESH_MS);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  if (data == null) return null;

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
      </section>
    );
  }

  const option = data.option;
  const costs = data.operating_costs;
  const cashFx = data.cash_fx;

  return (
    <section className="economicNavHost">
      <article className="economicNavPanel">
        <div className="economicHeader">
          <div>
            <span className="economicEyebrow">Investorjustert verdsettelse</span>
            <h2>Økonomisk NAV</h2>
          </div>
          <span className="economicBadge">ESTIMERT JUSTERING</span>
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
            <small>etter valutaeffekt og estimert drift</small>
          </div>
        </div>

        <div className="economicAdjustments">
          <div>
            <span>Kontanter – dokumentert valutaeffekt</span>
            <strong>{signedValue(cashFx?.adjustment_mnok)}</strong>
            <small>{cashFx?.coverage_pct != null ? `${value(cashFx.coverage_pct, 1)} % av kontantbeholdningen valutafordelt` : "–"}</small>
          </div>
          <div>
            <span>Opsjon – regnskapsført</span>
            <strong>{value(option?.accounting_liability_mnok, 1)} mill.</strong>
          </div>
          <div>
            <span>Opsjon – økonomisk verdi</span>
            <strong>{value(option?.economic_value_mnok, 1)} mill.</strong>
          </div>
          <div>
            <span>Ekstra opsjonsoverheng</span>
            <strong>−{value(option?.unrecognized_overhang_mnok, 1)} mill.</strong>
          </div>
          <div>
            <span>Estimert drift siden {dateLabel(costs?.anchor_date)}</span>
            <strong>−{value(costs?.base_mnok, 1)} mill.</strong>
          </div>
        </div>

        <div className="economicFootnote">
          <span>
            Årlig driftskostnadsnivå: ca. USD {value(costs?.base_annualized_usd_m, 2)} mill.
            {costs?.source_period ? ` (${costs.source_period})` : ""}.
            Kun dokumenterte USD-/BRL-kontanter revalueres; ukjent valutafordeling gjettes ikke. Renteinntekter er ikke lagt til.
          </span>
          <span>Data {dateLabel(data.as_of_date)}</span>
        </div>
      </article>
    </section>
  );
}

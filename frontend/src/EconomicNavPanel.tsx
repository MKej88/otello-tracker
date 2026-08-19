import { useEffect, useState } from "react";
import "./economic-nav.css";

type CashFxComponent = {
  currency?: string;
  usd_equivalent_at_anchor?: number | null;
  original_currency_amount?: number | null;
  anchor_value_mnok?: number | null;
  current_value_mnok?: number | null;
  adjustment_mnok?: number | null;
  quality?: string;
};

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
    current_usd_nok?: number | null;
    current_brl_nok?: number | null;
    components?: CashFxComponent[];
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

type CashCurrencyEstimate = {
  currency: "NOK" | "USD" | "BRL";
  share_pct: number;
  value_mnok: number;
  local_millions: number | null;
  basis: string;
};

type FxBacktestPeriod = {
  ready: boolean;
  reason?: string;
  period_start?: string;
  period_end?: string;
  model_cash_fx_usd_m?: number | null;
  actual_cash_fx_usd_m?: number | null;
  reported_pnl_fx_usd_m?: number | null;
  error_usd_m?: number | null;
  absolute_error_usd_m?: number | null;
  accuracy_pct?: number | null;
  sign_correct?: boolean;
  applied_known_movements?: number;
  skipped_movements?: number;
  unmodelled_end_cash_gap_usd_m?: number | null;
};

type FxBacktest = {
  ready: boolean;
  reason?: string;
  periods?: FxBacktestPeriod[];
  summary?: {
    periods_ready?: number;
    periods_total?: number;
    mean_absolute_error_usd_m?: number | null;
    sign_hit_rate_pct?: number | null;
  };
  method_note?: string;
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

function signedUsd(input: number | null | undefined, digits = 2) {
  if (input == null || !Number.isFinite(input)) return "–";
  const prefix = input > 0 ? "+" : "";
  return `${prefix}USD ${value(input, digits)} mill.`;
}

function dateLabel(input?: string | null) {
  if (!input) return "–";
  const [year, month, day] = input.split("-");
  if (!year || !month || !day) return input;
  return `${day}.${month}.${year}`;
}

function yearLabel(input?: string | null) {
  if (!input) return "–";
  return input.slice(0, 4);
}

function reasonLabel(reason?: string) {
  if (reason === "api_error") return "API-feil";
  return "Ikke klart";
}

function backtestReason(reason?: string) {
  if (reason === "missing_historical_fx_rates" || reason === "no_backtest_period_ready") {
    return "Historiske valutakurser mangler";
  }
  if (reason === "missing_fx_anchor") return "Historisk valutaanker mangler";
  if (reason === "missing_reported_fx_outcomes") return "Rapportert valutaeffekt mangler";
  if (reason === "api_error") return "Backtest-API utilgjengelig";
  return "Backtest ikke klar";
}

function daysBetween(from?: string, to?: string) {
  if (!from || !to) return null;
  const start = Date.parse(`${from}T00:00:00Z`);
  const end = Date.parse(`${to}T00:00:00Z`);
  if (!Number.isFinite(start) || !Number.isFinite(end)) return null;
  return Math.max(0, Math.round((end - start) / 86_400_000));
}

function confidenceLabel(anchorDate?: string, asOfDate?: string) {
  const days = daysBetween(anchorDate, asOfDate);
  if (days == null) return "UKJENT";
  if (days <= 45) return "MIDDELS–HØY";
  if (days <= 120) return "MIDDELS";
  return "LAV";
}

function cashCurrencyEstimate(data: EconomicNav): CashCurrencyEstimate[] | null {
  const cashFx = data.cash_fx;
  const components = cashFx?.components ?? [];
  const targetCash = data.economic_cash_mnok;
  if (targetCash == null || !Number.isFinite(targetCash) || targetCash <= 0 || components.length === 0) {
    return null;
  }

  const usd = components.find((item) => item.currency === "USD");
  const brl = components.find((item) => item.currency === "BRL");
  const nok = components.find((item) => item.currency === "NOK");
  const legacyResidual = components.find((item) => item.currency === "UNALLOCATED");
  const nokComponent = nok ?? legacyResidual;
  if (!usd || !brl || !nokComponent) return null;

  const rawNok = nokComponent.current_value_mnok ?? nokComponent.anchor_value_mnok ?? 0;
  const rawUsd = usd.current_value_mnok ?? usd.anchor_value_mnok ?? 0;
  const rawBrl = brl.current_value_mnok ?? brl.anchor_value_mnok ?? 0;
  const rawTotal = rawNok + rawUsd + rawBrl;
  if (!Number.isFinite(rawTotal) || rawTotal <= 0) return null;

  const scale = targetCash / rawTotal;
  const share = (amount: number) => amount / rawTotal * 100;

  return [
    {
      currency: "NOK",
      share_pct: share(rawNok),
      value_mnok: rawNok * scale,
      local_millions: nokComponent.original_currency_amount != null
        ? nokComponent.original_currency_amount * scale / 1_000_000
        : rawNok * scale,
      basis: nok ? "Avstemt NOK-residual" : "Estimert residual"
    },
    {
      currency: "USD",
      share_pct: share(rawUsd),
      value_mnok: rawUsd * scale,
      local_millions: usd.original_currency_amount != null
        ? usd.original_currency_amount * scale / 1_000_000
        : null,
      basis: "Rapportert eksponering"
    },
    {
      currency: "BRL",
      share_pct: share(rawBrl),
      value_mnok: rawBrl * scale,
      local_millions: brl.original_currency_amount != null
        ? brl.original_currency_amount * scale / 1_000_000
        : null,
      basis: "Rapportert eksponering"
    }
  ];
}

function localCashLabel(item: CashCurrencyEstimate) {
  if (item.local_millions == null) return `${value(item.value_mnok, 1)} mill. kr`;
  if (item.currency === "NOK") return `${value(item.local_millions, 1)} mill. kr`;
  if (item.currency === "USD") return `USD ${value(item.local_millions, 2)} mill.`;
  return `R$ ${value(item.local_millions, 1)} mill.`;
}

export default function EconomicNavPanel() {
  const [data, setData] = useState<EconomicNav | null>(null);
  const [backtest, setBacktest] = useState<FxBacktest | null>(null);

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

      fetch("/api/dashboard/fx-backtest")
        .then((response) => {
          if (!response.ok) throw new Error("FX backtest API-feil");
          return response.json() as Promise<FxBacktest>;
        })
        .then((result) => {
          if (active) setBacktest(result);
        })
        .catch(() => {
          if (active) setBacktest({ ready: false, reason: "api_error" });
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
  const currencyEstimate = cashCurrencyEstimate(data);
  const currencyConfidence = confidenceLabel(cashFx?.anchor_date, data.as_of_date);
  const readyBacktestPeriods = backtest?.periods?.filter((period) => period.ready) ?? [];
  const fullCashFxCoverage = cashFx?.quality === "FULL_EXPOSURE_REVALUATION";

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

        {currencyEstimate && (
          <div className="cashCurrencyEstimate">
            <div className="cashCurrencyHeader">
              <div>
                <span className="economicEyebrow">Valutaestimat</span>
                <h3>Estimert kontantbeholdning per valuta</h3>
              </div>
              <span className="cashConfidence">
                {fullCashFxCoverage ? "ANKER 100 % KILDEBASERT" : `SIKKERHET ${currencyConfidence}`}
              </span>
            </div>
            <div className="cashCurrencyGrid">
              {currencyEstimate.map((item) => (
                <div className="cashCurrencyCard" key={item.currency}>
                  <span>{item.currency}</span>
                  <strong>{localCashLabel(item)}</strong>
                  <small>{value(item.share_pct, 1)} % · {value(item.value_mnok, 1)} mill. kr</small>
                  <small>{item.basis}</small>
                </div>
              ))}
            </div>
            <div className="cashCurrencyNote">
              <span>
                På rapportankeret er USD- og BRL-eksponeringen rapportert direkte. NOK er avstemt som residual
                mellom total rapportert kontantbeholdning og USD/BRL, støttet av selskapets opplysning om at
                konsernets kontantinnskudd holdes i NOK, USD og BRL. NOK-residualen er derfor avledet og
                kildebasert, ikke et direkte rapportert NOK-tall.
              </span>
              <span>
                Etter ankerdatoen er faktisk valutaveksling ikke offentlig kjent. Fordelingen av senere netto
                kontantendringer er derfor fortsatt et estimat. Anker {dateLabel(cashFx?.anchor_date)}.
              </span>
            </div>
          </div>
        )}

        <div className="fxBacktest">
          <div className="cashCurrencyHeader">
            <div>
              <span className="economicEyebrow">Modellkontroll</span>
              <h3>Backtest av valutaeffekt</h3>
            </div>
            {backtest?.ready && (
              <span className="cashConfidence">
                {readyBacktestPeriods.length} PERIODER · RETNING {value(backtest.summary?.sign_hit_rate_pct, 0)} %
              </span>
            )}
          </div>

          {backtest?.ready ? (
            <>
              <div className="fxBacktestGrid">
                {readyBacktestPeriods.map((period) => (
                  <div className="fxBacktestCard" key={`${period.period_start}-${period.period_end}`}>
                    <div className="fxBacktestYear">
                      <strong>{yearLabel(period.period_end)}</strong>
                      <span className={period.sign_correct ? "fxBacktestHit" : "fxBacktestMiss"}>
                        {period.sign_correct ? "RIKTIG RETNING" : "FEIL RETNING"}
                      </span>
                    </div>
                    <dl>
                      <div>
                        <dt>Modellert cash-effekt</dt>
                        <dd>{signedUsd(period.model_cash_fx_usd_m)}</dd>
                      </div>
                      <div>
                        <dt>Faktisk cash-effekt</dt>
                        <dd>{signedUsd(period.actual_cash_fx_usd_m)}</dd>
                      </div>
                      <div>
                        <dt>Avvik</dt>
                        <dd>{signedUsd(period.error_usd_m)}</dd>
                      </div>
                      <div>
                        <dt>Treffgrad</dt>
                        <dd>{value(period.accuracy_pct, 0)} %</dd>
                      </div>
                    </dl>
                    <small>
                      Resultatført valutaresultat: {signedUsd(period.reported_pnl_fx_usd_m)} · kjente strømmer: {period.applied_known_movements ?? 0}
                    </small>
                  </div>
                ))}
              </div>
              <div className="fxBacktestSummary">
                <span>
                  Gjennomsnittlig absolutt avvik: USD {value(backtest.summary?.mean_absolute_error_usd_m, 2)} mill.
                </span>
                <span>
                  Fasiten er valutaeffekt på kontanter i kontantstrømoppstillingen. Resultatført valutaresultat vises kun som kontroll.
                </span>
              </div>
            </>
          ) : (
            <div className="fxBacktestUnavailable">
              <strong>{backtestReason(backtest?.reason)}</strong>
              <span>Backtesten påvirker ikke NAV og blir synlig når historiske valutaankre og kurser er komplette.</span>
            </div>
          )}
        </div>

        <div className="economicAdjustments">
          <div>
            <span>Kontanter – kildebasert valutaeffekt</span>
            <strong>{signedValue(cashFx?.adjustment_mnok)}</strong>
            <small>{cashFx?.coverage_pct != null ? `${value(cashFx.coverage_pct, 1)} % av rapportankeret valutafordelt` : "–"}</small>
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
            USD-/BRL-kontanter revalueres løpende; kildebasert NOK holdes i NOK. Renteinntekter er ikke lagt til.
          </span>
          <span>Data {dateLabel(data.as_of_date)}</span>
        </div>
      </article>
    </section>
  );
}

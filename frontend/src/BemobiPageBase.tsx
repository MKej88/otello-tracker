import { useEffect, useState } from "react";
import { fetchPreloadedJson } from "./navigationDataPreload";
import ResourceNotice from "./ResourceNotice";
import "./bemobi-page.css";

type ValuationScenario = {
  multiple: number;
  implied_price_brl: number;
  upside_pct: number;
};

type ValuationSourceQuarter = {
  period: string;
  adjusted_net_income_mbrl?: number | null;
  adjusted_ebitda_mbrl?: number | null;
  adjusted_cash_generation_mbrl?: number | null;
  harmonized_net_revenue_mbrl?: number | null;
  reported_revenue_mbrl?: number | null;
  reported_ebit_mbrl?: number | null;
  reported_net_income_parent_mbrl?: number | null;
  reported_operating_cash_flow_mbrl?: number | null;
  reported_capex_cash_outflow_mbrl?: number | null;
  reported_net_debt_mbrl?: number | null;
  source_url?: string | null;
  harmonized_net_revenue_source_url?: string | null;
};

type ForwardEstimate = {
  year?: number | null;
  net_income_mbrl?: number | null;
  ebitda_mbrl?: number | null;
  net_debt_mbrl?: number | null;
  market_cap_mbrl?: number | null;
  enterprise_value_mbrl?: number | null;
  pe?: number | null;
  earnings_yield_pct?: number | null;
  ev_ebitda?: number | null;
};

type BemobiConsensus = {
  ready: boolean;
  broker_estimates?: {
    source?: string | null;
    source_url?: string | null;
    published_date?: string | null;
    year_range?: string | null;
    years?: ForwardEstimate[];
  };
};

type BemobiDashboard = {
  ready: boolean;
  reason?: string;
  market?: {
    price_brl?: number | null;
    price_date?: string | null;
    price_source?: string | null;
  };
  valuation?: {
    period?: string | null;
    market_cap_mbrl?: number | null;
    net_cash_mbrl?: number | null;
    pe_ttm?: number | null;
    adjusted_fcf_yield_pct?: number | null;
    ev_ebit_ttm?: number | null;
    scenarios?: ValuationScenario[];
    source_quarters?: ValuationSourceQuarter[];
  };
  latest_result?: {
    period?: string | null;
    period_end?: string | null;
    published_date?: string | null;
    adjusted_net_revenue_mbrl?: number | null;
    adjusted_net_revenue_yoy_pct?: number | null;
    adjusted_ebitda_mbrl?: number | null;
    adjusted_ebitda_yoy_pct?: number | null;
    adjusted_ebitda_margin_pct?: number | null;
    adjusted_net_income_mbrl?: number | null;
    adjusted_net_income_yoy_pct?: number | null;
    ebitda_less_capex_mbrl?: number | null;
    cash_conversion_pct?: number | null;
    payments_yoy_pct?: number | null;
    saas_yoy_pct?: number | null;
    source_code?: string | null;
    source_url?: string | null;
  };
  next_report?: {
    period?: string | null;
    date?: string | null;
    date_quality?: string | null;
    label?: string | null;
    source_url?: string | null;
  };
};

const AUTO_REFRESH_MS = 2 * 60 * 1000;

function value(input: number | null | undefined, digits = 1) {
  if (input == null || !Number.isFinite(input)) return "–";
  return input.toLocaleString("nb-NO", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function signedPct(input: number | null | undefined, digits = 1) {
  if (input == null || !Number.isFinite(input)) return "–";
  return `${input > 0 ? "+" : ""}${value(input, digits)} %`;
}

function dateLabel(input?: string | null) {
  if (!input) return "–";
  const [year, month, day] = input.split("-");
  return year && month && day ? `${day}.${month}.${year}` : input;
}

function quarterIndex(period: string) {
  const match = /^([1-4])Q(\d{2})$/.exec(period.trim());
  if (!match) return null;
  return (2000 + Number(match[2])) * 4 + Number(match[1]) - 1;
}

function completeTtm(
  quarters: ValuationSourceQuarter[],
  field: keyof ValuationSourceQuarter,
) {
  if (quarters.length !== 4) return null;
  const indexes = quarters.map((quarter) => quarterIndex(quarter.period));
  if (indexes.some((current, index) => (
    current == null || (index > 0 && current !== Number(indexes[index - 1]) + 1)
  ))) return null;
  const values = quarters.map((quarter) => quarter[field]);
  if (values.some((item) => typeof item !== "number" || !Number.isFinite(item))) return null;
  return values.reduce<number>((sum, item) => sum + Number(item), 0);
}

function metricTone(input: number | null | undefined) {
  if (input == null || !Number.isFinite(input) || input === 0) return "";
  return input > 0 ? "positive" : "negative";
}

function selectForwardEstimates(
  years: ForwardEstimate[],
  asOfDate?: string | null,
) {
  const sorted = years
    .filter((item) => typeof item.year === "number" && Number.isFinite(item.year))
    .sort((a, b) => Number(a.year) - Number(b.year));
  if (!sorted.length) return { primary: null, secondary: null };

  const asOfYear = Number(String(asOfDate ?? "").slice(0, 4));
  const primary = Number.isFinite(asOfYear) && asOfYear > 2000
    ? sorted.find((item) => Number(item.year) === asOfYear)
      ?? sorted.find((item) => Number(item.year) > asOfYear)
      ?? sorted.at(-1)
      ?? null
    : sorted[0] ?? null;
  const primaryYear = typeof primary?.year === "number" ? primary.year : null;
  const secondary = primaryYear == null
    ? null
    : sorted.find((item) => Number(item.year) > primaryYear) ?? null;

  return { primary, secondary };
}

export default function BemobiPageBase() {
  const [data, setData] = useState<BemobiDashboard | null>(null);
  const [consensus, setConsensus] = useState<BemobiConsensus | null>(null);
  const [failed, setFailed] = useState(false);
  const [consensusFailed, setConsensusFailed] = useState(false);

  useEffect(() => {
    let active = true;

    const loadDashboard = (initial = false) => {
      const request = initial
        ? fetchPreloadedJson<BemobiDashboard>("/api/bemobi/dashboard")
        : fetch("/api/bemobi/dashboard").then((response) => {
            if (!response.ok) throw new Error("Bemobi dashboard API-feil");
            return response.json() as Promise<BemobiDashboard>;
          });
      request
        .then((result) => {
          if (!active) return;
          setData(result);
          setFailed(false);
        })
        .catch(() => {
          if (!active) return;
          setFailed(true);
        });
    };

    const loadConsensus = (initial = false) => {
      const request = initial
        ? fetchPreloadedJson<BemobiConsensus>("/api/bemobi/consensus")
        : fetch("/api/bemobi/consensus").then((response) => {
            if (!response.ok) throw new Error("Bemobi konsensus API-feil");
            return response.json() as Promise<BemobiConsensus>;
          });
      request
        .then((result) => {
          if (!active) return;
          setConsensus(result);
          setConsensusFailed(false);
        })
        .catch(() => {
          if (!active) return;
          setConsensusFailed(true);
        });
    };

    loadDashboard(true);
    loadConsensus(true);
    const timer = window.setInterval(() => {
      loadDashboard(false);
      loadConsensus(false);
    }, AUTO_REFRESH_MS);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  if (data == null && !failed) {
    return <ResourceNotice>Laster Bemobi-data …</ResourceNotice>;
  }

  if (failed && data == null) {
    return (
      <ResourceNotice kind="error">
        <strong>Kunne ikke hente Bemobi-data.</strong>
        <span>Investorvisningen er midlertidig utilgjengelig.</span>
      </ResourceNotice>
    );
  }

  if (!data?.ready) {
    return (
      <div className="bemobiNotice">
        <strong>Bemobi-siden mangler et aktivt datagrunnlag.</strong>
        <span>{data?.reason ?? "Venter på markeds- og resultatdata."}</span>
      </div>
    );
  }

  const market = data.market;
  const result = data.latest_result;
  const valuation = data.valuation;
  const nextReport = data.next_report;
  const quarters = valuation?.source_quarters ?? [];
  const latestQuarter = quarters.at(-1);

  const reportedNetIncomeTtm = completeTtm(quarters, "reported_net_income_parent_mbrl");
  const adjustedEbitdaTtm = completeTtm(quarters, "adjusted_ebitda_mbrl");
  const latestNetDebt = latestQuarter?.reported_net_debt_mbrl;
  const netCashMbrl = typeof latestNetDebt === "number"
    ? -latestNetDebt
    : valuation?.net_cash_mbrl ?? null;
  const enterpriseValueMbrl = valuation?.market_cap_mbrl == null || latestNetDebt == null
    ? null
    : valuation.market_cap_mbrl + latestNetDebt;
  const peTtm = valuation?.market_cap_mbrl != null && reportedNetIncomeTtm != null && reportedNetIncomeTtm > 0
    ? valuation.market_cap_mbrl / reportedNetIncomeTtm
    : valuation?.pe_ttm ?? null;
  const evEbitdaTtm = enterpriseValueMbrl != null && adjustedEbitdaTtm != null && adjustedEbitdaTtm > 0
    ? enterpriseValueMbrl / adjustedEbitdaTtm
    : null;
  const opFcfYield = valuation?.adjusted_fcf_yield_pct ?? null;
  const netCashToMarketCap = valuation?.market_cap_mbrl != null && valuation.market_cap_mbrl > 0 && netCashMbrl != null
    ? netCashMbrl / valuation.market_cap_mbrl * 100
    : null;

  const brokerEstimates = consensus?.ready ? consensus.broker_estimates : null;
  const { primary: forwardEstimate, secondary: nextEstimate } = selectForwardEstimates(
    brokerEstimates?.years ?? [],
    market?.price_date,
  );
  const forwardYear = typeof forwardEstimate?.year === "number" ? forwardEstimate.year : null;
  const nextYear = typeof nextEstimate?.year === "number" ? nextEstimate.year : null;
  const forwardLabel = forwardYear == null ? "TTM" : `${forwardYear}E`;
  const forwardPe = forwardEstimate?.pe ?? peTtm;
  const forwardEvEbitda = forwardEstimate?.ev_ebitda ?? evEbitdaTtm;
  const payoutYield = forwardEstimate?.earnings_yield_pct ?? null;
  const nextPe = nextEstimate?.pe ?? null;
  const nextEvEbitda = nextEstimate?.ev_ebitda ?? null;
  const nextPayoutYield = nextEstimate?.earnings_yield_pct ?? null;
  const valuationPeriodLabel = forwardYear == null
    ? valuation?.period ?? "TTM"
    : nextYear == null
      ? `TTM + ${forwardYear}E`
      : `${forwardYear}E + ${nextYear}E`;
  const forwardEps = market?.price_brl != null && market.price_brl > 0 && forwardPe != null && forwardPe > 0
    ? market.price_brl / forwardPe
    : null;
  const forwardScenarios = forwardEps == null || market?.price_brl == null || market.price_brl <= 0
    ? valuation?.scenarios ?? []
    : [12, 14, 16].map((multiple) => {
        const impliedPrice = forwardEps * multiple;
        return {
          multiple,
          implied_price_brl: impliedPrice,
          upside_pct: (impliedPrice / market.price_brl! - 1) * 100,
        };
      });

  return (
    <div className="bemobiPage bemobiPageClean">
      <section className="card bemobiCleanHero">
        <div>
          <span className="label">BEMOBI</span>
          <h2>Hvordan går Bemobi operasjonelt?</h2>
          <p>Siste resultat, vekst, kontantgenerering og verdsettelse – uten Otello/NAV-detaljer som finnes på egne sider.</p>
        </div>
        <div className="bemobiHeroQuote">
          <span>BMOB3</span>
          <strong>{market?.price_brl == null ? "–" : `R$ ${value(market.price_brl, 2)}`}</strong>
          <small>{dateLabel(market?.price_date)}</small>
        </div>
      </section>

      {failed && (
        <ResourceNotice>
          Ny oppdatering feilet. Siden viser sist vellykket hentede Bemobi-data.
        </ResourceNotice>
      )}

      <section className="bemobiCleanKpiGrid">
        <article className="card bemobiCleanKpi">
          <span className="label">Omsetning</span>
          <strong>R$ {value(result?.adjusted_net_revenue_mbrl, 1)}m</strong>
          <small className={metricTone(result?.adjusted_net_revenue_yoy_pct)}>{signedPct(result?.adjusted_net_revenue_yoy_pct)} år/år</small>
        </article>
        <article className="card bemobiCleanKpi">
          <span className="label">Justert EBITDA</span>
          <strong>R$ {value(result?.adjusted_ebitda_mbrl, 1)}m</strong>
          <small className={metricTone(result?.adjusted_ebitda_yoy_pct)}>{signedPct(result?.adjusted_ebitda_yoy_pct)} år/år</small>
        </article>
        <article className="card bemobiCleanKpi">
          <span className="label">EBITDA-margin</span>
          <strong>{value(result?.adjusted_ebitda_margin_pct, 1)} %</strong>
          <small>{result?.period ?? "Siste kvartal"}</small>
        </article>
        <article className="card bemobiCleanKpi">
          <span className="label">Justert resultat</span>
          <strong>R$ {value(result?.adjusted_net_income_mbrl, 1)}m</strong>
          <small className={metricTone(result?.adjusted_net_income_yoy_pct)}>{signedPct(result?.adjusted_net_income_yoy_pct)} år/år</small>
        </article>
      </section>

      <section className="bemobiCleanTwinGrid">
        <article className="card bemobiCleanSection">
          <div className="cardHeader">
            <div>
              <span className="label">VEKSTDRIVERE</span>
              <h2>Hva driver veksten?</h2>
            </div>
            <span className="pill">{result?.period ?? "SISTE"}</span>
          </div>
          <div className="bemobiDriverGrid">
            <div>
              <span>Payments</span>
              <strong className={metricTone(result?.payments_yoy_pct)}>{signedPct(result?.payments_yoy_pct, 0)}</strong>
              <small>år/år</small>
            </div>
            <div>
              <span>SaaS</span>
              <strong className={metricTone(result?.saas_yoy_pct)}>{signedPct(result?.saas_yoy_pct, 0)}</strong>
              <small>år/år</small>
            </div>
          </div>
          <p className="bemobiCleanNote">
            Samlet rapportert omsetningsvekst i kvartalet: <strong>{signedPct(result?.adjusted_net_revenue_yoy_pct)}</strong>.
          </p>
        </article>

        <article className="card bemobiCleanSection">
          <div className="cardHeader">
            <div>
              <span className="label">KONTANTGENERERING</span>
              <h2>Hvor mye blir til cash?</h2>
            </div>
          </div>
          <div className="bemobiCashMetricGrid">
            <div>
              <span>EBITDA − capex</span>
              <strong>R$ {value(result?.ebitda_less_capex_mbrl, 1)}m</strong>
              <small>siste kvartal</small>
            </div>
            <div>
              <span>Cash conversion</span>
              <strong>{value(result?.cash_conversion_pct, 1)} %</strong>
              <small>rapportert av Bemobi</small>
            </div>
            <div>
              <span>Netto cash</span>
              <strong>R$ {value(netCashMbrl, 1)}m</strong>
              <small>{latestQuarter?.period ?? valuation?.period ?? "TTM"}</small>
            </div>
          </div>
        </article>
      </section>

      <section className="card bemobiCleanValuation">
        <div className="cardHeader">
          <div>
            <span className="label">VERDSETTELSE</span>
            <h2>Hva betaler markedet?</h2>
          </div>
          <span className="pill">{valuationPeriodLabel}</span>
        </div>

        <div className="bemobiCleanValuationGrid bemobiCleanValuationGridFive">
          <div>
            <span>P/E {forwardLabel}</span>
            <strong>{value(forwardPe, 1)}x</strong>
            <small>{nextYear == null ? `TTM ${value(peTtm, 1)}x` : `${nextYear}E ${value(nextPe, 1)}x · TTM ${value(peTtm, 1)}x`}</small>
          </div>
          <div>
            <span>EV / EBITDA {forwardLabel}</span>
            <strong>{value(forwardEvEbitda, 1)}x</strong>
            <small>{nextYear == null ? `TTM ${value(evEbitdaTtm, 1)}x` : `${nextYear}E ${value(nextEvEbitda, 1)}x · TTM ${value(evEbitdaTtm, 1)}x`}</small>
          </div>
          <div>
            <span>Est. payout yield</span>
            <strong>{value(payoutYield, 1)} %</strong>
            <small>{nextYear == null ? `100 % av ${forwardLabel} resultat` : `${nextYear}E ${value(nextPayoutYield, 1)} % · 100 % payout`}</small>
          </div>
          <div>
            <span>OpFCF yield TTM</span>
            <strong>{value(opFcfYield, 1)} %</strong>
            <small>justert EBITDA − capex</small>
          </div>
          <div>
            <span>Net cash / MCap</span>
            <strong>{value(netCashToMarketCap, 1)} %</strong>
            <small>R$ {value(netCashMbrl, 1)}m netto cash</small>
          </div>
        </div>

        <div className="bemobiValuationSources">
          <span>TTM og OpFCF: Bemobi/CVM · markedsverdi: BMOB3</span>
          {brokerEstimates?.source_url && forwardYear != null ? (
            <a href={brokerEstimates.source_url} target="_blank" rel="noreferrer">
              Meglergrunnlag {nextYear == null ? forwardLabel : `${forwardLabel}–${nextYear}E`}: {brokerEstimates.source ?? "meglerestimat"} · {dateLabel(brokerEstimates.published_date)} →
            </a>
          ) : consensusFailed ? (
            <span>Forward-estimat kunne ikke oppdateres; TTM vises der mulig.</span>
          ) : null}
        </div>

        <div className="bemobiCleanScenarioBlock">
          <div className="bemobiCleanSectionTitle">
            <strong>Multipelsensitivitet</strong>
            <span>{forwardYear == null ? "Justert EPS · ikke kursmål" : `${forwardYear}E EPS · ikke kursmål`}</span>
          </div>
          <div className="bemobiCleanScenarioGrid">
            {forwardScenarios.map((scenario) => (
              <div key={scenario.multiple}>
                <span>{value(scenario.multiple, 0)}x P/E</span>
                <strong>R$ {value(scenario.implied_price_brl, 2)}</strong>
                <small className={metricTone(scenario.upside_pct)}>{signedPct(scenario.upside_pct)} mot BMOB3</small>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="card bemobiCleanHistory">
        <div className="cardHeader">
          <div>
            <span className="label">KVARTALSUTVIKLING</span>
            <h2>Siste fire rapporterte kvartaler</h2>
          </div>
        </div>
        <div className="bemobiQuarterTableWrap">
          <table className="bemobiQuarterTable">
            <thead>
              <tr>
                <th>Kvartal</th>
                <th>Omsetning</th>
                <th>Justert EBITDA</th>
                <th>Margin</th>
                <th>Justert resultat</th>
              </tr>
            </thead>
            <tbody>
              {quarters.map((quarter) => {
                const revenue = quarter.harmonized_net_revenue_mbrl ?? quarter.reported_revenue_mbrl ?? null;
                const ebitda = quarter.adjusted_ebitda_mbrl ?? null;
                const margin = revenue != null && revenue > 0 && ebitda != null
                  ? ebitda / revenue * 100
                  : null;
                return (
                  <tr key={quarter.period}>
                    <td><strong>{quarter.period}</strong></td>
                    <td>R$ {value(revenue, 1)}m</td>
                    <td>R$ {value(ebitda, 1)}m</td>
                    <td>{value(margin, 1)} %</td>
                    <td>R$ {value(quarter.adjusted_net_income_mbrl, 1)}m</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <section className="card bemobiCleanWatch">
        <div className="cardHeader">
          <div>
            <span className="label">FREMOVER</span>
            <h2>Det viktigste å følge</h2>
          </div>
        </div>
        <div className="bemobiWatchGrid">
          <div>
            <span>Payments-vekst</span>
            <strong className={metricTone(result?.payments_yoy_pct)}>{signedPct(result?.payments_yoy_pct, 0)}</strong>
            <small>år/år</small>
          </div>
          <div>
            <span>SaaS-vekst</span>
            <strong className={metricTone(result?.saas_yoy_pct)}>{signedPct(result?.saas_yoy_pct, 0)}</strong>
            <small>år/år</small>
          </div>
          <div>
            <span>Cash conversion</span>
            <strong>{value(result?.cash_conversion_pct, 1)} %</strong>
            <small>siste kvartal</small>
          </div>
          <div>
            <span>Neste rapport</span>
            <strong>{nextReport?.date ? dateLabel(nextReport.date) : "Ikke bekreftet"}</strong>
            <small>{nextReport?.period ?? "Neste kvartal"}</small>
          </div>
        </div>
        <div className="bemobiCleanFooterMeta">
          <span>Siste rapport: {result?.period ?? "–"} · publisert {dateLabel(result?.published_date)}</span>
          {result?.source_url && (
            <a href={result.source_url} target="_blank" rel="noreferrer">Åpne resultatkilden →</a>
          )}
          {nextReport?.source_url && (
            <a href={nextReport.source_url} target="_blank" rel="noreferrer">Bemobi-kalender →</a>
          )}
        </div>
      </section>
    </div>
  );
}

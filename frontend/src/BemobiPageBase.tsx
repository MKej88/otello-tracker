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

export default function BemobiPageBase() {
  const [data, setData] = useState<BemobiDashboard | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    const load = (initial = false) => {
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

    load(true);
    const timer = window.setInterval(load, AUTO_REFRESH_MS);
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
  const reportedEbitTtm = completeTtm(quarters, "reported_ebit_mbrl");
  const reportedOperatingCashFlowTtm = completeTtm(quarters, "reported_operating_cash_flow_mbrl");
  const reportedCapexCashOutflowTtm = completeTtm(quarters, "reported_capex_cash_outflow_mbrl");
  const reportedCapexTtm = reportedCapexCashOutflowTtm == null
    ? null
    : Math.abs(reportedCapexCashOutflowTtm);
  const reportedFcfTtm = reportedOperatingCashFlowTtm == null || reportedCapexTtm == null
    ? null
    : reportedOperatingCashFlowTtm - reportedCapexTtm;
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
  const evEbitTtm = enterpriseValueMbrl != null && reportedEbitTtm != null && reportedEbitTtm > 0
    ? enterpriseValueMbrl / reportedEbitTtm
    : valuation?.ev_ebit_ttm ?? null;
  const fcfYield = valuation?.market_cap_mbrl != null && reportedFcfTtm != null
    ? reportedFcfTtm / valuation.market_cap_mbrl * 100
    : valuation?.adjusted_fcf_yield_pct ?? null;

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
          <span className="pill">{valuation?.period ?? "TTM"}</span>
        </div>

        <div className="bemobiCleanValuationGrid">
          <div>
            <span>P/E TTM</span>
            <strong>{value(peTtm, 1)}x</strong>
            <small>rapportert resultat når komplett</small>
          </div>
          <div>
            <span>EV / EBIT</span>
            <strong>{value(evEbitTtm, 1)}x</strong>
            <small>TTM</small>
          </div>
          <div>
            <span>FCF yield</span>
            <strong>{value(fcfYield, 1)} %</strong>
            <small>CVM CFO − capex når komplett</small>
          </div>
          <div>
            <span>Netto cash</span>
            <strong>R$ {value(netCashMbrl, 1)}m</strong>
            <small>siste tilgjengelige balanse</small>
          </div>
        </div>

        <div className="bemobiCleanScenarioBlock">
          <div className="bemobiCleanSectionTitle">
            <strong>Multipelsensitivitet</strong>
            <span>Justert EPS · ikke kursmål</span>
          </div>
          <div className="bemobiCleanScenarioGrid">
            {(valuation?.scenarios ?? []).map((scenario) => (
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

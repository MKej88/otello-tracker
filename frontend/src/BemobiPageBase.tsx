import { useEffect, useState } from "react";
import { fetchPreloadedJson } from "./navigationDataPreload";
import ResourceNotice from "./ResourceNotice";
import BemobiSourceStatusPanel from "./BemobiSourceStatusPanel";
import "./bemobi-page.css";

type Source = {
  label: string;
  source: string;
  url?: string | null;
};

type ValuationScenario = {
  multiple: number;
  implied_price_brl: number;
  upside_pct: number;
};

type ValuationSourceQuarter = {
  period: string;
  adjusted_net_income_mbrl: number;
  adjusted_ebitda_mbrl: number;
  adjusted_cash_generation_mbrl?: number | null;
  harmonized_net_revenue_mbrl?: number | null;
  harmonized_net_revenue_source_url?: string | null;
  reported_revenue_mbrl?: number | null;
  reported_ebit_mbrl?: number | null;
  reported_net_income_parent_mbrl?: number | null;
  reported_operating_cash_flow_mbrl?: number | null;
  reported_capex_cash_outflow_mbrl?: number | null;
  reported_capex_cash_outflow_account?: string | null;
  reported_cash_mbrl?: number | null;
  reported_borrowings_mbrl?: number | null;
  reported_net_debt_mbrl?: number | null;
  reported_net_income_parent_source_url?: string | null;
  reported_revenue_source_url?: string | null;
  source: string;
  source_url?: string | null;
};

type BemobiDashboard = {
  ready: boolean;
  reason?: string;
  as_of_date?: string | null;
  market?: {
    price_brl?: number | null;
    price_date?: string | null;
    price_source?: string | null;
    price_quality?: string | null;
    brl_nok?: number | null;
    brl_nok_date?: string | null;
  };
  otello?: {
    shares?: number | null;
    ownership_pct?: number | null;
    value_brl_m?: number | null;
    value_nok_m?: number | null;
    value_per_otello_share_nok?: number | null;
  };
  valuation?: {
    period?: string | null;
    ttm_end_period?: string | null;
    market_cap_mbrl?: number | null;
    enterprise_value_mbrl?: number | null;
    net_debt_mbrl?: number | null;
    net_cash_mbrl?: number | null;
    ev_anchor_period?: string | null;
    ev_anchor_status?: string | null;
    ev_anchor_is_current?: boolean;
    ev_metrics_ready?: boolean;
    ev_anchor_quality?: string | null;
    ev_anchor_source?: string | null;
    ev_anchor_source_url?: string | null;
    adjusted_net_income_ttm_mbrl?: number | null;
    reported_net_income_ttm_mbrl?: number | null;
    reported_net_income_ttm_complete?: boolean;
    reported_net_income_source?: string | null;
    reported_net_income_source_url?: string | null;
    adjusted_ebitda_ttm_mbrl?: number | null;
    adjusted_fcf_ttm_mbrl?: number | null;
    ebit_ttm_mbrl?: number | null;
    adjusted_eps_ttm_brl?: number | null;
    pe_ttm?: number | null;
    price_to_ebitda_ttm?: number | null;
    earnings_yield_pct?: number | null;
    adjusted_fcf_yield_pct?: number | null;
    ev_ebit_ttm?: number | null;
    scenarios?: ValuationScenario[];
    source_quarters?: ValuationSourceQuarter[];
    methodology_note?: string | null;
  };
  latest_result?: {
    period?: string;
    period_end?: string;
    published_date?: string;
    adjusted_net_revenue_mbrl?: number | null;
    adjusted_net_revenue_yoy_pct?: number | null;
    adjusted_ebitda_mbrl?: number | null;
    adjusted_ebitda_yoy_pct?: number | null;
    adjusted_ebitda_margin_pct?: number | null;
    adjusted_net_income_mbrl?: number | null;
    adjusted_net_income_yoy_pct?: number | null;
    ebitda_less_capex_mbrl?: number | null;
    cash_conversion_pct?: number | null;
    cash_mbrl?: number | null;
    payments_yoy_pct?: number | null;
    saas_yoy_pct?: number | null;
    source_code?: string | null;
    source_url?: string | null;
    source_title?: string | null;
  };
  distribution_estimate?: {
    ready: boolean;
    reason?: string | null;
    period?: string | null;
    ttm_end_period?: string | null;
    reported_net_income_ttm_mbrl?: number | null;
    payout_policy_pct?: number | null;
    policy_year?: number | null;
    policy_is_current?: boolean;
    estimated_total_distribution_mbrl?: number | null;
    otello_distribution_share_pct?: number | null;
    distribution_eligible_shares?: number | null;
    ownership_method?: string | null;
    otello_gross_mbrl?: number | null;
    otello_gross_mnok?: number | null;
    otello_gross_per_otec_share_nok?: number | null;
    brl_nok?: number | null;
    source_code?: string | null;
    source_url?: string | null;
    methodology_note?: string | null;
  };
  latest_distribution?: {
    type?: string | null;
    announcement_date?: string | null;
    record_date?: string | null;
    ex_date?: string | null;
    payment_date?: string | null;
    gross_per_share_brl?: number | null;
    net_per_share_brl?: number | null;
    gross_total_mbrl?: number | null;
    net_total_mbrl?: number | null;
    withholding_rate_pct?: number | null;
    tax_treatment?: string | null;
    otello_gross_mbrl?: number | null;
    otello_net_mbrl?: number | null;
    source_code?: string | null;
    source_url?: string | null;
    source_title?: string | null;
  } | null;
  next_report?: {
    period?: string | null;
    date?: string | null;
    date_quality?: string | null;
    label?: string | null;
    source_url?: string | null;
  };
  sources?: Source[];
  note?: string;
};

const AUTO_REFRESH_MS = 2 * 60 * 1000;
const integer = new Intl.NumberFormat("nb-NO", { maximumFractionDigits: 0 });

function value(input: number | null | undefined, digits = 1) {
  if (input == null || !Number.isFinite(input)) return "–";
  return input.toLocaleString("nb-NO", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits
  });
}

function signedValue(input: number | null | undefined, digits = 1) {
  if (input == null || !Number.isFinite(input)) return "–";
  const prefix = input > 0 ? "+" : "";
  return `${prefix}${value(input, digits)} %`;
}

function growthValue(input: number | null | undefined, digits = 1) {
  return input == null || !Number.isFinite(input) ? "–" : signedValue(input, digits);
}

function dateLabel(input?: string | null) {
  if (!input) return "–";
  const [year, month, day] = input.split("-");
  return year && month && day ? `${day}.${month}.${year}` : input;
}

function distributionLabel(input?: string | null) {
  if (input === "JCP") return "Renter";
  if (input === "DIVIDEND") return "Utbytte";
  return input || "Utbetaling";
}

function sourceName(input?: string | null) {
  const names: Record<string, string> = {
    CVM: "CVM",
    B3: "B3",
    BRAPI: "brapi.dev",
    BEMOBI_IR: "Bemobi IR"
  };
  return input ? names[input] ?? input : "Kilde ikke oppgitt";
}

function quarterIndex(period: string) {
  const match = /^([1-4])Q(\d{2})$/.exec(period.trim());
  if (!match) return null;
  return (2000 + Number(match[2])) * 4 + Number(match[1]) - 1;
}

function completeTtm(
  quarters: ValuationSourceQuarter[],
  field: keyof ValuationSourceQuarter
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

function SourceLink({ url, children }: { url?: string | null; children: React.ReactNode }) {
  if (!url) return <span>{children}</span>;
  return <a href={url} target="_blank" rel="noreferrer">{children}</a>;
}

export default function BemobiPage({
  onData,
}: {
  onData?: (data: BemobiDashboard) => void;
}) {
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
          onData?.(result);
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
  }, [onData]);

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
        <span>{data?.reason ?? "Venter på markeds- og NAV-data."}</span>
      </div>
    );
  }

  const market = data.market;
  const otello = data.otello;
  const valuation = data.valuation;
  const result = data.latest_result;
  const distributionEstimate = data.distribution_estimate;
  const distribution = data.latest_distribution;
  const nextReport = data.next_report;
  const ttmRange = valuation?.period?.replace(/^TTM\s+/, "") ?? "TTM";
  const evAnchorPeriod = valuation?.ev_anchor_period ?? "ukjent periode";
  const cvmQuarters = valuation?.source_quarters ?? [];
  const latestCvm = cvmQuarters.at(-1);
  const harmonizedRevenueTtm = completeTtm(cvmQuarters, "harmonized_net_revenue_mbrl");
  const reportedRevenueTtm = completeTtm(cvmQuarters, "reported_revenue_mbrl");
  const reportedEbitTtm = completeTtm(cvmQuarters, "reported_ebit_mbrl");
  const reportedNetIncomeTtm = completeTtm(cvmQuarters, "reported_net_income_parent_mbrl");
  const reportedOperatingCashFlowTtm = completeTtm(cvmQuarters, "reported_operating_cash_flow_mbrl");
  const reportedCapexCashOutflowTtm = completeTtm(cvmQuarters, "reported_capex_cash_outflow_mbrl");
  const reportedCapexTtm = reportedCapexCashOutflowTtm == null ? null : Math.abs(reportedCapexCashOutflowTtm);
  const reportedFcfTtm =
    reportedOperatingCashFlowTtm == null || reportedCapexTtm == null
      ? null
      : reportedOperatingCashFlowTtm - reportedCapexTtm;
  const cvmNetDebt = latestCvm?.reported_net_debt_mbrl;
  const cvmNetCash = typeof cvmNetDebt === "number" ? -cvmNetDebt : null;
  const cvmEnterpriseValue =
    valuation?.market_cap_mbrl == null || cvmNetDebt == null
      ? null
      : valuation.market_cap_mbrl + cvmNetDebt;
  const cvmPe =
    valuation?.market_cap_mbrl == null || reportedNetIncomeTtm == null || reportedNetIncomeTtm <= 0
      ? null
      : valuation.market_cap_mbrl / reportedNetIncomeTtm;
  const cvmEvEbit =
    cvmEnterpriseValue == null || reportedEbitTtm == null || reportedEbitTtm <= 0
      ? null
      : cvmEnterpriseValue / reportedEbitTtm;
  const cvmEarningsYield =
    valuation?.market_cap_mbrl == null || reportedNetIncomeTtm == null
      ? null
      : reportedNetIncomeTtm / valuation.market_cap_mbrl * 100;
  const cvmFcfYield =
    valuation?.market_cap_mbrl == null || reportedFcfTtm == null
      ? null
      : reportedFcfTtm / valuation.market_cap_mbrl * 100;
  const adjustedCapexTtm =
    valuation?.adjusted_ebitda_ttm_mbrl == null || valuation?.adjusted_fcf_ttm_mbrl == null
      ? null
      : valuation.adjusted_ebitda_ttm_mbrl - valuation.adjusted_fcf_ttm_mbrl;
  const capexTtmDelta =
    reportedCapexTtm == null || adjustedCapexTtm == null
      ? null
      : reportedCapexTtm - adjustedCapexTtm;
  const adjustedCapexQuarter =
    result?.adjusted_ebitda_mbrl == null || result?.ebitda_less_capex_mbrl == null
      ? null
      : result.adjusted_ebitda_mbrl - result.ebitda_less_capex_mbrl;
  const cvmCapexQuarter =
    latestCvm?.reported_capex_cash_outflow_mbrl == null
      ? null
      : Math.abs(latestCvm.reported_capex_cash_outflow_mbrl);
  const capexQuarterDelta =
    cvmCapexQuarter == null || adjustedCapexQuarter == null
      ? null
      : cvmCapexQuarter - adjustedCapexQuarter;
  const cvmCapexAccount = latestCvm?.reported_capex_cash_outflow_account;
  const cvmEvReady = cvmEvEbit != null;
  const evAnchorStale = !cvmEvReady && valuation?.ev_anchor_is_current === false;
  const pePrimary = cvmPe ?? valuation?.pe_ttm;
  const evEbitPrimary = cvmEvEbit ?? valuation?.ev_ebit_ttm;
  const fcfYieldPrimary = cvmFcfYield ?? valuation?.adjusted_fcf_yield_pct;
  const earningsYieldPrimary = cvmEarningsYield ?? valuation?.earnings_yield_pct;

  const topCards = [
    {
      label: "BMOB3-kurs",
      main: market?.price_brl == null ? "–" : `R$ ${value(market.price_brl, 2)}`,
      sub: `${sourceName(market?.price_source)} · ${dateLabel(market?.price_date)}`
    },
    {
      label: "Otellos eierandel",
      main: otello?.ownership_pct == null ? "–" : `${value(otello.ownership_pct, 2)} %`,
      sub: otello?.shares == null ? "–" : `${integer.format(otello.shares)} Bemobi-aksjer`
    },
    {
      label: "Verdi for Otello",
      main: otello?.value_nok_m == null ? "–" : `${value(otello.value_nok_m, 1)} mill. kr`,
      sub: otello?.value_brl_m == null ? "–" : `R$ ${value(otello.value_brl_m, 1)} mill.`
    },
    {
      label: "Verdi per OTEC-aksje",
      main: otello?.value_per_otello_share_nok == null ? "–" : `${value(otello.value_per_otello_share_nok, 2)} kr`,
      sub: market?.brl_nok == null ? "–" : `BRL/NOK ${value(market.brl_nok, 4)}`
    }
  ];

  return (
    <div className="bemobiPage">
      <section className="bemobiHero card">
        <div>
          <span className="label">BEMOBI / BMOB3</span>
          <h2>Otellos største underliggende verdi</h2>
          <p>
            Løpende markedsverdi av Otellos Bemobi-post, siste rapporterte nøkkeltall,
            verdsettelse og kontantutdelinger samlet i én investorvisning.
          </p>
        </div>
        <div className="bemobiHeroMeta">
          <span className="pill">BMOB3</span>
          <span>Markedsdata {dateLabel(market?.price_date)}</span>
        </div>
      </section>

      <section className="bemobiKpiGrid">
        {topCards.map((card) => (
          <article className="card bemobiKpi" key={card.label}>
            <span className="label">{card.label}</span>
            <strong>{card.main}</strong>
            <span>{card.sub}</span>
          </article>
        ))}
      </section>

      <section className="card bemobiValuation">
        <div className="cardHeader">
          <div>
            <span className="label">Verdsettelse nå · CVM-first</span>
            <h2>Hva betaler markedet for Bemobi?</h2>
          </div>
          <span className="pill">{valuation?.period ?? "TTM"}</span>
        </div>

        {evAnchorStale && (
          <p className="bemobiValuationNote">
            <strong>CVM-balanse/EBIT er ikke komplett ennå.</strong> Legacy EV-ankeret er eldre enn TTM-grunnlaget.
            Enterprise value og EV/EBIT vises derfor først når CVM-grunnlaget eller et ferskt anker er tilgjengelig.
          </p>
        )}

        <div className="bemobiValuationMetrics">
          <div>
            <span>Markedsverdi</span>
            <strong>R$ {value(valuation?.market_cap_mbrl, 0)}m</strong>
            <small>B3-kurs × aksjer</small>
          </div>
          <div>
            <span>P/E TTM</span>
            <strong>{value(pePrimary, 1)}x</strong>
            <small>{cvmPe != null ? "Rapportert CVM-resultat" : "Justert fallback"}</small>
          </div>
          <div>
            <span>EV / EBIT TTM</span>
            <strong>{value(evEbitPrimary, 1)}x</strong>
            <small>{cvmEvEbit != null ? "CVM EBIT + CVM netto gjeld" : `Fallback · anker ${evAnchorPeriod}`}</small>
          </div>
          <div>
            <span>FCF yield</span>
            <strong>{value(fcfYieldPrimary, 1)} %</strong>
            <small>{cvmFcfYield != null ? "CVM CFO − capex" : "FCF yield (just.) fallback"}</small>
          </div>
          <div>
            <span>Earnings yield</span>
            <strong>{value(earningsYieldPrimary, 1)} %</strong>
            <small>{cvmEarningsYield != null ? "Rapportert CVM-resultat" : "Justert fallback"}</small>
          </div>
          <div>
            <span>Markedsverdi / EBITDA</span>
            <strong>{value(valuation?.price_to_ebitda_ttm, 1)}x</strong>
            <small>Justert EBITDA · Bemobi</small>
          </div>
        </div>

        <div className="bemobiValuationBody">
          <div className="bemobiSensitivity">
            <div className="bemobiSectionTitle">
              <span>Multipelsensitivitet</span>
              <small>Justert EPS · ikke kursmål</small>
            </div>
            <div className="bemobiScenarioGrid">
              {(valuation?.scenarios ?? []).map((scenario) => (
                <div key={scenario.multiple}>
                  <span>{value(scenario.multiple, 0)}x P/E</span>
                  <strong>R$ {value(scenario.implied_price_brl, 2)}</strong>
                  <small className={scenario.upside_pct >= 0 ? "positive" : "negative"}>
                    {signedValue(scenario.upside_pct, 1)} mot dagens kurs
                  </small>
                </div>
              ))}
            </div>
          </div>

          <div className="bemobiValuationBase">
            <div className="bemobiSectionTitle">
              <span>TTM-grunnlag · Bemobi + CVM</span>
              <small>{ttmRange}</small>
            </div>
            <div className="placeholderRows">
              <div><span>Harmonisert nettoomsetning TTM · Bemobi/CVM release</span><strong>R$ {value(harmonizedRevenueTtm, 1)}m</strong></div>
              <div><span>Regnskapsført omsetning TTM · CVM 3.01 · kontroll</span><strong>R$ {value(reportedRevenueTtm, 1)}m</strong></div>
              <div><span>Rapportert EBIT TTM · CVM 3.05</span><strong>R$ {value(reportedEbitTtm, 1)}m</strong></div>
              <div><span>Rapportert resultat TTM · CVM 3.11.01</span><strong>R$ {value(reportedNetIncomeTtm ?? valuation?.reported_net_income_ttm_mbrl, 1)}m</strong></div>
              <div><span>Operasjonell kontantstrøm TTM · CVM 6.01</span><strong>R$ {value(reportedOperatingCashFlowTtm, 1)}m</strong></div>
              <div><span>Capex TTM · CVM DFC</span><strong>R$ {value(reportedCapexTtm, 1)}m</strong></div>
              <div><span>FCF TTM · CVM CFO − capex</span><strong>R$ {value(reportedFcfTtm, 1)}m</strong></div>
              <div><span>Netto kontant · CVM {latestCvm?.period ?? "siste"}</span><strong>R$ {value(cvmNetCash, 1)}m</strong></div>
              <div><span>Enterprise value · CVM-first</span><strong>R$ {value(cvmEnterpriseValue, 0)}m</strong></div>
              <div><span>Justert resultat TTM · Bemobi</span><strong>R$ {value(valuation?.adjusted_net_income_ttm_mbrl, 1)}m</strong></div>
              <div><span>Justert EBITDA TTM · Bemobi</span><strong>R$ {value(valuation?.adjusted_ebitda_ttm_mbrl, 1)}m</strong></div>
              <div><span>Justert FCF-proxy TTM</span><strong>R$ {value(valuation?.adjusted_fcf_ttm_mbrl, 1)}m</strong></div>
              <div><span>Justert capex TTM · EBITDA − FCF-proxy</span><strong>R$ {value(adjustedCapexTtm, 1)}m</strong></div>
            </div>
          </div>
        </div>

        <p className="bemobiValuationNote">
          <strong>Omsetning:</strong> Harmonisert nettoomsetning fra Bemobis offisielle resultatrapport brukes som
          hovedmål fordi M4U-bruttoføringen ellers blåser opp både omsetning og kostnader. CVM DRE 3.01 beholdes
          uendret som regulatorisk kontrolltall.
        </p>

        {(reportedCapexTtm != null || adjustedCapexTtm != null) && (
          <p className="bemobiValuationNote">
            <strong>Capex-avstemming:</strong> CVM DFC viser R$ {value(reportedCapexTtm, 1)}m TTM,
            mens Bemobis justerte definisjon impliserer R$ {value(adjustedCapexTtm, 1)}m.
            {capexTtmDelta != null && ` Differanse: R$ ${value(capexTtmDelta, 1)}m.`}
            {" "}CVM-kontokoden kan endres mellom rapporter; trackeren følger beskrivelsen for kjøp av
            imobilizado/intangível og lagrer faktisk kontokode som proveniens. Definisjonene kan ha ulikt
            omfang, så CVM-linjen brukes som regulatorisk kontroll – ikke som automatisk erstatning for Bemobis justerte capex.
          </p>
        )}

        <div className="bemobiQuarterSources">
          <span>Resultatgrunnlag:</span>
          {cvmQuarters.map((quarter) => (
            <SourceLink
              key={quarter.period}
              url={quarter.harmonized_net_revenue_source_url ?? quarter.reported_net_income_parent_source_url ?? quarter.reported_revenue_source_url ?? quarter.source_url}
            >
              <span>
                {quarter.period} · {quarter.reported_net_income_parent_mbrl != null ? "CVM ITR/DFP" : quarter.source}
              </span>
            </SourceLink>
          ))}
          {!cvmEvReady && (
            <SourceLink url={valuation?.ev_anchor_source_url}>
              <span>Legacy EV-anker {evAnchorPeriod} · {valuation?.ev_anchor_source ?? "CVM"}</span>
            </SourceLink>
          )}
        </div>
        {valuation?.methodology_note && <p className="bemobiValuationNote">{valuation.methodology_note}</p>}
      </section>

      <section className="bemobiTwoColumn">
        <article className="card bemobiResults">
          <div className="cardHeader">
            <div>
              <span className="label">Siste rapport · CVM-first</span>
              <h2>{result?.period ?? latestCvm?.period ?? "–"} · nøkkeltall</h2>
            </div>
            <SourceLink url={latestCvm?.reported_net_income_parent_source_url ?? result?.source_url}>
              <span className="pill">{latestCvm?.reported_net_income_parent_mbrl != null ? "CVM" : sourceName(result?.source_code)}</span>
            </SourceLink>
          </div>

          <div className="bemobiResultGrid">
            <div>
              <span>Harmonisert nettoomsetning</span>
              <strong>R$ {value(result?.adjusted_net_revenue_mbrl ?? latestCvm?.harmonized_net_revenue_mbrl, 1)}m</strong>
              <em>Bemobi/CVM release</em>
            </div>
            <div>
              <span>Regnskapsført omsetning</span>
              <strong>R$ {value(latestCvm?.reported_revenue_mbrl, 1)}m</strong>
              <em>CVM 3.01 · kontroll</em>
            </div>
            <div>
              <span>Rapportert EBIT</span>
              <strong>R$ {value(latestCvm?.reported_ebit_mbrl, 1)}m</strong>
              <em>CVM 3.05</em>
            </div>
            <div>
              <span>Resultat til Bemobi-aksjonærer</span>
              <strong>R$ {value(latestCvm?.reported_net_income_parent_mbrl ?? result?.adjusted_net_income_mbrl, 1)}m</strong>
              <em>{latestCvm?.reported_net_income_parent_mbrl != null ? "CVM 3.11.01" : "Justert fallback"}</em>
            </div>
            <div>
              <span>Operasjonell kontantstrøm</span>
              <strong>R$ {value(latestCvm?.reported_operating_cash_flow_mbrl, 1)}m</strong>
              <em>CVM 6.01</em>
            </div>
            <div>
              <span>Capex</span>
              <strong>R$ {value(cvmCapexQuarter, 1)}m</strong>
              <em>{cvmCapexAccount ? `CVM ${cvmCapexAccount}` : "CVM DFC"}</em>
            </div>
            <div>
              <span>Kontantbeholdning</span>
              <strong>R$ {value(latestCvm?.reported_cash_mbrl ?? result?.cash_mbrl, 0)}m</strong>
              <em>{latestCvm?.reported_cash_mbrl != null ? "CVM 1.01.01" : "Bemobi fallback"}</em>
            </div>
          </div>

          <div className="bemobiSectionTitle">
            <span>Bemobi-justerte KPI-er</span>
            <small>Offisiell resultatpresentasjon</small>
          </div>
          <div className="placeholderRows">
            <div><span>Justert EBITDA</span><strong>R$ {value(result?.adjusted_ebitda_mbrl, 1)}m · {value(result?.adjusted_ebitda_margin_pct, 1)} % margin</strong></div>
            <div><span>Justert resultat</span><strong>R$ {value(result?.adjusted_net_income_mbrl, 1)}m</strong></div>
            <div><span>EBITDA etter capex</span><strong>R$ {value(result?.ebitda_less_capex_mbrl, 1)}m · {value(result?.cash_conversion_pct, 1)} % konvertering</strong></div>
          </div>

          {(cvmCapexQuarter != null || adjustedCapexQuarter != null) && (
            <p className="bemobiValuationNote">
              Capex-avstemming {latestCvm?.period ?? result?.period}: CVM DFC
              {cvmCapexAccount ? ` (${cvmCapexAccount})` : ""} R$ {value(cvmCapexQuarter, 1)}m
              mot Bemobi-justert implisitt capex R$ {value(adjustedCapexQuarter, 1)}m.
              {capexQuarterDelta != null && ` Differanse R$ ${value(capexQuarterDelta, 1)}m.`}
            </p>
          )}

          <div className="bemobiGrowthStrip">
            <div><span>Payments</span><strong>{growthValue(result?.payments_yoy_pct, 0)}</strong><small>år/år</small></div>
            <div><span>SaaS</span><strong>{growthValue(result?.saas_yoy_pct, 0)}</strong><small>år/år</small></div>
            <div><span>Rapportdato</span><strong>{dateLabel(result?.published_date)}</strong><small>{result?.period}</small></div>
          </div>
        </article>

        <article className="card bemobiStake">
          <div className="cardHeader">
            <div><span className="label">Otellos eksponering</span><h2>Bemobi-posten</h2></div>
            <span className="pill muted">{value(otello?.ownership_pct, 2)} %</span>
          </div>
          <div className="bemobiStakeValue">
            <strong>{otello?.shares == null ? "–" : integer.format(otello.shares)}</strong>
            <span>Bemobi-aksjer eid av Otello</span>
          </div>
          <div className="placeholderRows">
            <div><span>Eierandel</span><strong>{value(otello?.ownership_pct, 2)} %</strong></div>
            <div><span>Markedsverdi i BRL</span><strong>R$ {value(otello?.value_brl_m, 1)} mill.</strong></div>
            <div><span>Markedsverdi i NOK</span><strong>{value(otello?.value_nok_m, 1)} mill. kr</strong></div>
            <div><span>Verdi per OTEC-aksje</span><strong>{value(otello?.value_per_otello_share_nok, 2)} kr</strong></div>
          </div>
        </article>
      </section>

      <section className="card bemobiValuation">
        <div className="cardHeader">
          <div>
            <span className="label">Kapitalretur · TTM run-rate</span>
            <h2>Estimert utbytte til Otello</h2>
          </div>
          <SourceLink url={distributionEstimate?.source_url}>
            <span className="pill">{distributionEstimate?.ready ? sourceName(distributionEstimate.source_code) : "CVM"}</span>
          </SourceLink>
        </div>

        {distributionEstimate?.ready ? (
          <>
            <div className="bemobiValuationMetrics">
              <div>
                <span>Otello brutto</span>
                <strong>{value(distributionEstimate.otello_gross_mnok, 1)} mill. kr</strong>
                <small>R$ {value(distributionEstimate.otello_gross_mbrl, 1)}m</small>
              </div>
              <div>
                <span>Per OTEC-aksje</span>
                <strong>{value(distributionEstimate.otello_gross_per_otec_share_nok, 2)} kr</strong>
                <small>Brutto run-rate</small>
              </div>
              <div>
                <span>Rapportert resultat TTM</span>
                <strong>R$ {value(distributionEstimate.reported_net_income_ttm_mbrl, 1)}m</strong>
                <small>{distributionEstimate.period}</small>
              </div>
              <div>
                <span>Otellos utdelingsandel</span>
                <strong>{value(distributionEstimate.otello_distribution_share_pct, 2)} %</strong>
                <small>
                  {distributionEstimate.ownership_method === "LATEST_DISTRIBUTION_ELIGIBLE_SHARES"
                    ? "Utbytteberettigede aksjer"
                    : "Rapportert eierandel"}
                </small>
              </div>
            </div>

            <div className="placeholderRows">
              <div>
                <span>Indikert Bemobi-utdeling</span>
                <strong>R$ {value(distributionEstimate.estimated_total_distribution_mbrl, 1)} mill.</strong>
              </div>
              <div>
                <span>Payout brukt i modellen</span>
                <strong>{value(distributionEstimate.payout_policy_pct, 0)} %</strong>
              </div>
              <div>
                <span>Policy / scenario</span>
                <strong>
                  {distributionEstimate.policy_is_current
                    ? `${distributionEstimate.policy_year} payout-policy`
                    : "100 % payout-scenario"}
                </strong>
              </div>
              <div>
                <span>BRL/NOK</span>
                <strong>{value(distributionEstimate.brl_nok, 4)}</strong>
              </div>
              {distributionEstimate.distribution_eligible_shares != null && (
                <div>
                  <span>Utbytteberettigede Bemobi-aksjer</span>
                  <strong>{integer.format(distributionEstimate.distribution_eligible_shares)}</strong>
                </div>
              )}
            </div>
            <p className="bemobiValuationNote">
              {distributionEstimate.methodology_note} Faktisk kontantbeløp kan avvike avhengig av
              styrevedtak, JCP/utbytte-miks, skatt og eventuell endring i payout-policy.
            </p>
          </>
        ) : (
          <p className="bemobiEmpty">
            Venter på fire sammenhengende kvartaler med rapportert CVM-resultat til Bemobis aksjonærer.
            Når CVM-grunnlaget er komplett oppdateres TTM-estimatet automatisk.
          </p>
        )}
      </section>

      <section className="bemobiTwoColumn">
        <article className="card bemobiDistribution">
          <div className="cardHeader">
            <div>
              <span className="label">Kapitalretur</span>
              <h2>Siste {distributionLabel(distribution?.type)}</h2>
            </div>
            {distribution && (
              <SourceLink url={distribution.source_url}>
                <span className="pill">{sourceName(distribution.source_code)}</span>
              </SourceLink>
            )}
          </div>
          {distribution ? (
            <div className="placeholderRows">
              <div><span>Brutto per Bemobi-aksje</span><strong>R$ {value(distribution.gross_per_share_brl, 8)}</strong></div>
              <div><span>Netto per Bemobi-aksje</span><strong>R$ {value(distribution.net_per_share_brl, 8)}</strong></div>
              <div><span>Otellos bruttoandel</span><strong>R$ {value(distribution.otello_gross_mbrl, 2)} mill.</strong></div>
              <div><span>Otellos estimerte nettoandel</span><strong>R$ {value(distribution.otello_net_mbrl, 2)} mill.</strong></div>
              <div><span>Ex-dato</span><strong>{dateLabel(distribution.ex_date)}</strong></div>
              <div><span>Betalingsdato</span><strong>{dateLabel(distribution.payment_date)}</strong></div>
            </div>
          ) : (
            <p className="bemobiEmpty">Ingen strukturert Bemobi-utbetaling tilgjengelig.</p>
          )}
        </article>

        <article className="card bemobiNextReport">
          <div className="cardHeader">
            <div><span className="label">Kommende rapport</span><h2>{nextReport?.period ?? "Neste kvartal"}</h2></div>
            <span className="pill muted">KALENDER</span>
          </div>
          <div className="bemobiCalendarDate">
            <strong>{nextReport?.date ? dateLabel(nextReport.date) : "Ikke bekreftet"}</strong>
            <span>{nextReport?.label ?? "Venter på offisiell dato fra Bemobi."}</span>
          </div>
          <p>
            Vi viser ikke en estimert rapportdato som om den var bekreftet. Når Bemobi publiserer
            datoen i sin offisielle kalender, kan den legges inn i datagrunnlaget.
          </p>
          <SourceLink url={nextReport?.source_url}>
            <span className="bemobiSourceAction">Åpne Bemobis hendelseskalender →</span>
          </SourceLink>
        </article>
      </section>

      <BemobiSourceStatusPanel />

      <section className="card bemobiSources">
        <div className="cardHeader"><div><span className="label">Kilder</span><h2>Hva tallene bygger på</h2></div></div>
        <div className="sourceList">
          {(data.sources ?? []).map((source) => (
            <div key={`${source.label}-${source.source}`}>
              <span>{source.label}</span>
              <strong>
                <SourceLink url={source.url}>{source.source}</SourceLink>
              </strong>
            </div>
          ))}
        </div>
        {data.note && <p className="bemobiFootnote">{data.note}</p>}
      </section>
    </div>
  );
}

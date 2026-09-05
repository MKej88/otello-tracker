import { useEffect, useMemo, useState } from "react";
import ResourceNotice from "./ResourceNotice";
import { formatDate, formatInteger, formatNumber } from "./uiFormat";
import "./cash-page.css";

type Summary = {
  ready: boolean;
  data_status?: string;
  as_of_date?: string | null;
  nav_per_share?: number | null;
  otec_price?: number | null;
  shares_outstanding?: number | null;
  cash_quality?: string | null;
  cash_calibration_quality?: string | null;
};

type BemobiDashboard = {
  ready: boolean;
  market?: {
    brl_nok?: number | null;
    brl_nok_date?: string | null;
  };
  otello?: {
    ownership_pct?: number | null;
  };
  valuation?: {
    net_cash_mbrl?: number | null;
  };
  latest_result?: {
    period?: string | null;
    period_end?: string | null;
    cash_mbrl?: number | null;
    adjusted_net_income_mbrl?: number | null;
    ebitda_less_capex_mbrl?: number | null;
    cash_conversion_pct?: number | null;
  };
  distribution_estimate?: {
    ready?: boolean;
    period?: string | null;
    ttm_end_period?: string | null;
    reported_net_income_ttm_mbrl?: number | null;
    payout_policy_pct?: number | null;
    policy_year?: number | null;
    policy_is_current?: boolean | null;
    estimated_total_distribution_mbrl?: number | null;
    otello_distribution_share_pct?: number | null;
    otello_gross_mbrl?: number | null;
    otello_gross_mnok?: number | null;
    otello_gross_per_otec_share_nok?: number | null;
    brl_nok?: number | null;
    ordinary_dividend_withholding_rate_pct?: number | null;
    jcp_withholding_rate_pct?: number | null;
    otello_net_dividend_mnok?: number | null;
    otello_net_jcp_mnok?: number | null;
    otello_net_dividend_per_otec_share_nok?: number | null;
    otello_net_jcp_per_otec_share_nok?: number | null;
    methodology_note?: string | null;
  };
};

type BuybackDashboard = {
  ready: boolean;
  program?: {
    remaining_shares?: number | null;
    max_price_nok?: number | null;
    cash_spent_nok?: number | string | null;
    progress_pct?: number | null;
  };
  shares?: {
    outstanding_shares?: number | null;
  };
};

type EconomicDashboard = {
  ready: boolean;
  as_of_date?: string | null;
  cash_bridge?: {
    report_date?: string | null;
    reported_cash_mnok?: number | null;
    estimated_cash_mnok?: number | null;
    cash_per_share_nok?: number | null;
    change_since_report_mnok?: number | null;
    movements?: Array<{
      key: string;
      label: string;
      amount_mnok?: number | null;
    }>;
  };
};

const AUTO_REFRESH_MS = 2 * 60 * 1000;
const INTEREST_SENSITIVITY_RATE_PCT = 14.25;
const JCP_WITHHOLDING_RATE_PCT = 15;
const JCP_1Q26_ACTUAL_MBRL = 16.0;
const JCP_2Q26_ACTUAL_MBRL = 16.0;
const JCP_3Q26_ESTIMATE_MBRL = 16.19;
const JCP_4Q26_ESTIMATE_MBRL = 16.0;

async function fetchJson<T>(url: string): Promise<T> {
  const response = await fetch(url, { headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`API-feil ${response.status} for ${url}`);
  return response.json() as Promise<T>;
}

function finite(input: number | string | null | undefined) {
  if (input == null || input === "") return null;
  const numeric = Number(input);
  return Number.isFinite(numeric) ? numeric : null;
}

function moneyM(input: number | null | undefined, digits = 1) {
  return input == null || !Number.isFinite(input)
    ? "–"
    : `${formatNumber(input, digits)} mill. kr`;
}

function pct(input: number | null | undefined, digits = 1) {
  return input == null || !Number.isFinite(input)
    ? "–"
    : `${formatNumber(input, digits)} %`;
}

function statusLabel(input?: string | null) {
  const labels: Record<string, string> = {
    REPORTED: "RAPPORTERT",
    ANCHORED_ESTIMATE: "ANKRET ESTIMAT",
    FORECAST_PARTIAL: "DELVIS PROGNOSE",
    ANCHORED: "ANKRET",
    HIGH_RESIDUAL: "HØYT RESTLEDD",
    GOOD: "GOD",
    HIGH: "HØY",
    MEDIUM: "MIDDELS",
    LOW: "LAV",
    UNKNOWN: "UKJENT",
  };
  if (!input) return "UKJENT";
  return labels[input.toUpperCase()] ?? input;
}

export default function CashPage() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [bemobi, setBemobi] = useState<BemobiDashboard | null>(null);
  const [economic, setEconomic] = useState<EconomicDashboard | null>(null);
  const [buyback, setBuyback] = useState<BuybackDashboard | null>(null);
  const [coreFailed, setCoreFailed] = useState(false);
  const [partialFailed, setPartialFailed] = useState(false);
  const [bufferM, setBufferM] = useState(30);
  const [priceAssumption, setPriceAssumption] = useState<number | null>(null);

  useEffect(() => {
    let active = true;

    const load = async () => {
      const [summaryResult, bemobiResult, economicResult, buybackResult] = await Promise.allSettled([
        fetchJson<Summary>("/api/dashboard/summary"),
        fetchJson<BemobiDashboard>("/api/bemobi/dashboard"),
        fetchJson<EconomicDashboard>("/api/dashboard/economic"),
        fetchJson<BuybackDashboard>("/api/buybacks/dashboard"),
      ]);

      if (!active) return;

      if (summaryResult.status === "fulfilled") {
        setSummary(summaryResult.value);
        setPriceAssumption((current) => current ?? summaryResult.value.otec_price ?? null);
      }
      if (bemobiResult.status === "fulfilled") setBemobi(bemobiResult.value);
      if (economicResult.status === "fulfilled") setEconomic(economicResult.value);
      if (buybackResult.status === "fulfilled") setBuyback(buybackResult.value);

      setCoreFailed(
        summaryResult.status === "rejected" ||
        bemobiResult.status === "rejected" ||
        economicResult.status === "rejected",
      );
      setPartialFailed(buybackResult.status === "rejected");
    };

    void load();
    const timer = window.setInterval(() => { void load(); }, AUTO_REFRESH_MS);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  const metrics = useMemo(() => {
    const cashBridge = economic?.cash_bridge;
    const directCashM = cashBridge?.estimated_cash_mnok ?? null;
    const ownershipPct = bemobi?.otello?.ownership_pct ?? null;
    const ownership = ownershipPct == null ? null : ownershipPct / 100;
    const bemobiCashMbrl = bemobi?.latest_result?.cash_mbrl ?? null;
    const brlNok = bemobi?.market?.brl_nok ?? null;
    const bemobiLookthroughMbrl =
      bemobiCashMbrl == null || ownership == null ? null : bemobiCashMbrl * ownership;
    const bemobiLookthroughMnok =
      bemobiLookthroughMbrl == null || brlNok == null
        ? null
        : bemobiLookthroughMbrl * brlNok;
    const combinedM =
      directCashM == null || bemobiLookthroughMnok == null
        ? null
        : directCashM + bemobiLookthroughMnok;
    const shares = summary?.shares_outstanding ?? buyback?.shares?.outstanding_shares ?? null;
    const directPerShare = cashBridge?.cash_per_share_nok ?? null;
    const combinedPerShare =
      combinedM == null || shares == null || shares <= 0
        ? null
        : combinedM * 1_000_000 / shares;
    const navTotalM =
      summary?.nav_per_share == null || shares == null
        ? null
        : summary.nav_per_share * shares / 1_000_000;
    const combinedPctNav =
      combinedM == null || navTotalM == null || navTotalM <= 0
        ? null
        : combinedM / navTotalM * 100;

    return {
      directCashM,
      ownershipPct,
      bemobiCashMbrl,
      bemobiLookthroughMbrl,
      bemobiLookthroughMnok,
      combinedM,
      shares,
      directPerShare,
      combinedPerShare,
      combinedPctNav,
      brlNok,
    };
  }, [summary, bemobi, economic, buyback]);

  const buybackCalc = useMemo(() => {
    const directCashM = metrics.directCashM;
    const shares = metrics.shares;
    const navPerShare = summary?.nav_per_share ?? null;
    const price = priceAssumption ?? summary?.otec_price ?? null;
    if (
      directCashM == null ||
      shares == null ||
      shares <= 0 ||
      navPerShare == null ||
      navPerShare <= 0 ||
      price == null ||
      price <= 0
    ) {
      return null;
    }

    const buffer = Math.min(Math.max(bufferM, 0), directCashM);
    const deployableM = Math.max(0, directCashM - buffer);
    const financialCapacityShares = deployableM * 1_000_000 / price;
    const remainingMandate = buyback?.program?.remaining_shares ?? null;
    const programMaxPrice = buyback?.program?.max_price_nok ?? null;
    const priceAllowed = programMaxPrice == null || price <= programMaxPrice;
    const mandateLimited =
      remainingMandate != null && Math.max(0, remainingMandate) < financialCapacityShares;
    const sharesBought = !priceAllowed
      ? 0
      : remainingMandate == null
        ? financialCapacityShares
        : Math.min(financialCapacityShares, Math.max(0, remainingMandate));
    const spendM = sharesBought * price / 1_000_000;
    const cashAfterM = Math.max(0, directCashM - spendM);
    const cashAboveBufferM = cashAfterM - buffer;
    const outstandingAfter = Math.max(1, shares - sharesBought);
    const navTotalM = navPerShare * shares / 1_000_000;
    const navAfterM = navTotalM - spendM;
    const navAfterPerShare = navAfterM * 1_000_000 / outstandingAfter;
    const accretionPct = (navAfterPerShare / navPerShare - 1) * 100;
    const discountToNavPct = (1 - price / navPerShare) * 100;
    const limitingFactor = !priceAllowed ? "PRICE" : mandateLimited ? "MANDATE" : "CASH";

    return {
      buffer,
      financialCapacityShares,
      remainingMandate,
      sharesBought,
      spendM,
      cashAfterM,
      cashAboveBufferM,
      navBeforePerShare: navPerShare,
      navAfterPerShare,
      accretionPct,
      discountToNavPct,
      limitingFactor,
      price,
    };
  }, [metrics, summary, buyback, bufferM, priceAssumption]);

  if (coreFailed && (!summary || !bemobi || !economic)) {
    return (
      <ResourceNotice kind="error">
        Kunne ikke hente cash- og kapitalallokeringsdata. Prøv å laste siden på nytt.
      </ResourceNotice>
    );
  }

  if (!summary || !bemobi || !economic) {
    return <ResourceNotice>Laster cash- og kapitalallokeringsdata …</ResourceNotice>;
  }

  const cashAsOfDate = economic.as_of_date ?? summary.as_of_date;
  const directShare = metrics.combinedM && metrics.directCashM != null
    ? metrics.directCashM / metrics.combinedM * 100
    : null;
  const indirectShare = directShare == null ? null : 100 - directShare;
  const interestProxyMbrl =
    metrics.bemobiCashMbrl == null
      ? null
      : metrics.bemobiCashMbrl * INTEREST_SENSITIVITY_RATE_PCT / 100;
  const interestProxyOtecMnok =
    interestProxyMbrl == null || metrics.ownershipPct == null || metrics.brlNok == null
      ? null
      : interestProxyMbrl * metrics.ownershipPct / 100 * metrics.brlNok;
  const maxBuffer = Math.max(50, Math.ceil(metrics.directCashM ?? 50));
  const maxPrice = Math.max(30, Math.ceil((summary.otec_price ?? 15) * 1.8));
  const programSpent = finite(buyback?.program?.cash_spent_nok);
  const programSpentMnok = programSpent == null ? null : Math.abs(programSpent) / 1_000_000;
  const buybackConstraintLabel = buybackCalc?.limitingFactor === "MANDATE"
    ? "MANDAT"
    : buybackCalc?.limitingFactor === "PRICE"
      ? "KURS"
      : "CASH";
  const buybackConstraintTitle = buybackCalc?.limitingFactor === "MANDATE"
    ? "Dagens mandat begrenser tilbakekjøpet"
    : buybackCalc?.limitingFactor === "PRICE"
      ? "Valgt kjøpskurs er over programmets makspris"
      : "Tilgjengelig cash begrenser tilbakekjøpet";

  const distribution = bemobi.distribution_estimate;
  const distributionSharePct = distribution?.otello_distribution_share_pct ?? metrics.ownershipPct;
  const distributionBrlNok = distribution?.brl_nok ?? metrics.brlNok;

  const jcpEstimate = (bemobiGrossMbrl: number) => {
    const grossOtecMbrl = distributionSharePct == null
      ? null
      : bemobiGrossMbrl * distributionSharePct / 100;
    const netOtecMbrl = grossOtecMbrl == null
      ? null
      : grossOtecMbrl * (1 - JCP_WITHHOLDING_RATE_PCT / 100);
    const netOtecMnok = netOtecMbrl == null || distributionBrlNok == null
      ? null
      : netOtecMbrl * distributionBrlNok;
    return { netOtecMnok };
  };

  const jcp3Q = jcpEstimate(JCP_3Q26_ESTIMATE_MBRL);
  const jcp4Q = jcpEstimate(JCP_4Q26_ESTIMATE_MBRL);
  const jcp2H26GrossMbrl = JCP_3Q26_ESTIMATE_MBRL + JCP_4Q26_ESTIMATE_MBRL;
  const jcp2H26NetOtecMnok =
    jcp3Q.netOtecMnok == null || jcp4Q.netOtecMnok == null
      ? null
      : jcp3Q.netOtecMnok + jcp4Q.netOtecMnok;
  const jcpFullYearGrossMbrl =
    JCP_1Q26_ACTUAL_MBRL +
    JCP_2Q26_ACTUAL_MBRL +
    JCP_3Q26_ESTIMATE_MBRL +
    JCP_4Q26_ESTIMATE_MBRL;

  return (
    <div className="investorPage cashPage">
      <section className="card cashHero">
        <div>
          <span className="label">CASH & KAPITALALLOKERING</span>
          <h2>Hvor mye cash finnes – og hva kan den gjøre for NAV?</h2>
          <p>
            Direkte Otello-cash skilles fra Otellos økonomiske andel av Bemobis cash.
            Siden viser også forventede utdelinger og effekten av tilbakekjøp under dagens NAV.
          </p>
        </div>
        <div className="cashHeroMeta">
          <span className="pill">OTEC + BMOB3</span>
          <span>OTEC-estimat {formatDate(cashAsOfDate)}</span>
          <span>Bemobi-balanse {formatDate(bemobi.latest_result?.period_end)}</span>
        </div>
      </section>

      {coreFailed && (
        <ResourceNotice kind="error">
          Ny oppdatering av hoveddata feilet. Siden viser sist vellykket hentede data.
        </ResourceNotice>
      )}
      {partialFailed && (
        <ResourceNotice>
          Tilbakekjøpsdata er midlertidig utilgjengelige. Cash- og Bemobi-tall vises fortsatt.
        </ResourceNotice>
      )}

      <section className="cashKpiGrid">
        <article className="card cashKpi">
          <span className="label">OTEC direkte cash</span>
          <strong>{moneyM(metrics.directCashM)}</strong>
          <small>{formatNumber(metrics.directPerShare, 2)} kr per OTEC-aksje</small>
        </article>
        <article className="card cashKpi">
          <span className="label">Bemobi look-through cash</span>
          <strong>{moneyM(metrics.bemobiLookthroughMnok)}</strong>
          <small>
            R$ {formatNumber(metrics.bemobiLookthroughMbrl, 1)}m · {formatNumber(metrics.ownershipPct, 2)} % eierandel
          </small>
        </article>
        <article className="card cashKpi cashKpiEmphasis">
          <span className="label">Samlet look-through cash</span>
          <strong>{moneyM(metrics.combinedM)}</strong>
          <small>{formatNumber(metrics.combinedPerShare, 2)} kr per OTEC-aksje</small>
        </article>
        <article className="card cashKpi">
          <span className="label">Cash som andel av NAV</span>
          <strong>{pct(metrics.combinedPctNav)}</strong>
          <small>Direkte + indirekte cash mot dagens NAV</small>
        </article>
      </section>

      <section className="cashMainGrid">
        <article className="card cashCompositionCard">
          <div className="cardHeader">
            <div>
              <span className="label">KONTANTSTRUKTUR</span>
              <h2>Direkte versus indirekte cash</h2>
            </div>
            <span className="pill">LOOK-THROUGH</span>
          </div>
          <div className="cashSplitBar" aria-label="Fordeling direkte og indirekte cash">
            <span className="cashSplitDirect" style={{ width: `${directShare ?? 0}%` }} />
            <span className="cashSplitIndirect" style={{ width: `${indirectShare ?? 0}%` }} />
          </div>
          <div className="cashLegendRows">
            <div>
              <span><i className="cashLegendSwatch direct" />Otello disponerer direkte</span>
              <strong>{moneyM(metrics.directCashM)}</strong>
              <small>{pct(directShare)} av look-through cash</small>
            </div>
            <div>
              <span><i className="cashLegendSwatch indirect" />Bundet i Bemobi</span>
              <strong>{moneyM(metrics.bemobiLookthroughMnok)}</strong>
              <small>{pct(indirectShare)} av look-through cash</small>
            </div>
          </div>
          <p className="cashNote">
            Bemobi-andelen er økonomisk look-through-verdi, ikke kontanter Otello kan disponere før Bemobi faktisk distribuerer kapitalen.
          </p>
        </article>

        <article className="card cashModelCard">
          <div className="cardHeader">
            <div>
              <span className="label">OTELLO CASH-MODELL</span>
              <h2>Estimert cash i dag</h2>
            </div>
            <span className="pill">{statusLabel(summary.cash_quality)}</span>
          </div>
          <div className="cashModelValue">
            <strong>{moneyM(metrics.directCashM)}</strong>
            <span>per {formatDate(cashAsOfDate)}</span>
          </div>
          <div className="placeholderRows cashModelRows">
            <div><span>Kontantkvalitet</span><strong>{statusLabel(summary.cash_quality)}</strong></div>
            <div><span>Kalibrering</span><strong>{statusLabel(summary.cash_calibration_quality)}</strong></div>
            <div><span>Cash per aksje</span><strong>{formatNumber(metrics.directPerShare, 2)} kr</strong></div>
            <div><span>Datastatus</span><strong>{statusLabel(summary.data_status)}</strong></div>
          </div>
        </article>
      </section>

      <section className="cashMainGrid">
        <article className="card cashEngineCard">
          <div className="cardHeader">
            <div>
              <span className="label">BEMOBI I DAG</span>
              <h2>Rapportert cash og kontantgenerering</h2>
            </div>
            <span className="pill">RAPPORTERT {bemobi.latest_result?.period ?? "SISTE KVARTAL"}</span>
          </div>
          <div className="cashMetricGrid">
            <div>
              <span>Cash</span>
              <strong>R$ {formatNumber(metrics.bemobiCashMbrl, 1)}m</strong>
              <small>{formatDate(bemobi.latest_result?.period_end)}</small>
            </div>
            <div>
              <span>Netto cash</span>
              <strong>R$ {formatNumber(bemobi.valuation?.net_cash_mbrl, 1)}m</strong>
              <small>verdsettelsesanker</small>
            </div>
            <div>
              <span>EBITDA − capex</span>
              <strong>R$ {formatNumber(bemobi.latest_result?.ebitda_less_capex_mbrl, 1)}m</strong>
              <small>siste kvartal</small>
            </div>
            <div>
              <span>Cash conversion</span>
              <strong>{pct(bemobi.latest_result?.cash_conversion_pct)}</strong>
              <small>rapportert av Bemobi</small>
            </div>
          </div>
          <p className="cashNote">
            Denne boksen viser rapporterte balanse- og kontantgenereringstall. Den inneholder ikke et estimat på fremtidige utdelinger.
          </p>
        </article>

        <article className="card cashDistributionCard">
          <div className="cardHeader">
            <div>
              <span className="label">FRA BEMOBI TIL OTEC</span>
              <h2>Utbyttemodell til Otello</h2>
            </div>
            <span className="pill">10 % KILDESKATT</span>
          </div>

          <div className="placeholderRows">
            <div>
              <span>Rapportert nettoresultat TTM</span>
              <strong>R$ {formatNumber(distribution?.reported_net_income_ttm_mbrl, 1)}m</strong>
            </div>
            <div>
              <span>× Payout-policy {distribution?.policy_year ?? "–"}</span>
              <strong>{pct(distribution?.payout_policy_pct, 0)}</strong>
            </div>
            <div>
              <span>= Modellert Bemobi-distribusjon</span>
              <strong>R$ {formatNumber(distribution?.estimated_total_distribution_mbrl, 1)}m</strong>
            </div>
            <div>
              <span>× Otellos distribusjonsandel</span>
              <strong>{pct(distribution?.otello_distribution_share_pct, 2)}</strong>
            </div>
            <div>
              <span>= Brutto til Otello</span>
              <strong>
                R$ {formatNumber(distribution?.otello_gross_mbrl, 1)}m · {moneyM(distribution?.otello_gross_mnok)}
              </strong>
            </div>
            <div>
              <span>− Brasiliansk kildeskatt på ordinært utbytte</span>
              <strong>{pct(distribution?.ordinary_dividend_withholding_rate_pct ?? 10, 0)}</strong>
            </div>
          </div>

          <div className="cashDistributionHeadline">
            <span>Netto cash til Otello – utbytteforutsetning</span>
            <strong>{moneyM(distribution?.otello_net_dividend_mnok)}</strong>
            <small>{formatNumber(distribution?.otello_net_dividend_per_otec_share_nok, 2)} kr per OTEC-aksje</small>
          </div>

          <div className="cashInterestStrip">
            <div>
              <span>BRL/NOK i modellen</span>
              <strong>{formatNumber(distributionBrlNok, 3)}</strong>
            </div>
            <div>
              <span>Skatteforutsetning</span>
              <strong>10 %</strong>
              <small>ordinært utbytte</small>
            </div>
          </div>

          <p className="cashNote">
            Hovedmodellen antar for enkelhets skyld at hele den modellerte 2026-distribusjonen utbetales som ordinært utbytte og ilegges 10 % brasiliansk kildeskatt. JCP-seksjonen nedenfor viser hvordan deler av denne payouten kan komme tidligere gjennom kvartalsvis JCP; beløpene skal ikke legges oppå hovedestimatet.
          </p>
        </article>
      </section>

      <section className="cashMainGrid">
        <article className="card cashDistributionCard">
          <div className="cardHeader">
            <div>
              <span className="label">KVARTALSVIS JCP</span>
              <h2>Faktisk 1H26 og estimat for 2H26</h2>
            </div>
            <span className="pill">15 % KILDESKATT</span>
          </div>

          <div className="cashMetricGrid">
            <div>
              <span>1Q26</span>
              <strong>R$ {formatNumber(JCP_1Q26_ACTUAL_MBRL, 1)}m</strong>
              <small>annonsert</small>
            </div>
            <div>
              <span>2Q26</span>
              <strong>R$ {formatNumber(JCP_2Q26_ACTUAL_MBRL, 1)}m</strong>
              <small>annonsert</small>
            </div>
            <div>
              <span>3Q26E</span>
              <strong>R$ {formatNumber(JCP_3Q26_ESTIMATE_MBRL, 1)}m</strong>
              <small>tracker-estimat · middels sikkerhet</small>
            </div>
            <div>
              <span>4Q26E</span>
              <strong>R$ {formatNumber(JCP_4Q26_ESTIMATE_MBRL, 1)}m</strong>
              <small>tracker-estimat · lavere sikkerhet</small>
            </div>
          </div>

          <div className="cashInterestStrip">
            <div>
              <span>Estimert JCP 3Q + 4Q</span>
              <strong>R$ {formatNumber(jcp2H26GrossMbrl, 1)}m</strong>
              <small>Bemobi brutto</small>
            </div>
            <div>
              <span>Estimert netto til Otello 3Q + 4Q</span>
              <strong>{moneyM(jcp2H26NetOtecMnok)}</strong>
              <small>etter 15 % kildeskatt · dagens BRL/NOK</small>
            </div>
          </div>

          <div className="placeholderRows">
            <div>
              <span>3Q26E netto til Otello</span>
              <strong>{moneyM(jcp3Q.netOtecMnok)}</strong>
            </div>
            <div>
              <span>4Q26E netto til Otello</span>
              <strong>{moneyM(jcp4Q.netOtecMnok)}</strong>
            </div>
            <div>
              <span>Helårs JCP 2026E</span>
              <strong>R$ {formatNumber(jcpFullYearGrossMbrl, 1)}m</strong>
            </div>
            <div>
              <span>Otellos distribusjonsandel brukt i modellen</span>
              <strong>{pct(distributionSharePct, 2)}</strong>
            </div>
          </div>

          <p className="cashNote">
            1Q26 og 2Q26 er annonserte JCP-beløp på R$16m per kvartal. 3Q26-estimatet er R$16,19m basert på den tidligere TJLP-modellen (9,14 %, om lag 92 dager og en implisitt JCP-base rundt R$703m). 4Q26 er satt til om lag R$16m med lavere sikkerhet. JCP behandles som timing/form på deler av Bemobis samlede 100 % payout og dobbelttelles derfor ikke mot utbyttemodellen over.
          </p>
        </article>

        <article className="card cashEngineCard">
          <div className="cardHeader">
            <div>
              <span className="label">RENTEINNTEKTER</span>
              <h2>Hva kan Bemobis cash tjene i renter?</h2>
            </div>
            <span className="pill">SENSITIVITET</span>
          </div>
          <div className="cashMetricGrid">
            <div>
              <span>Siste rapporterte cash</span>
              <strong>R$ {formatNumber(metrics.bemobiCashMbrl, 1)}m</strong>
              <small>{formatDate(bemobi.latest_result?.period_end)}</small>
            </div>
            <div>
              <span>Modellrente</span>
              <strong>{formatNumber(INTEREST_SENSITIVITY_RATE_PCT, 2)} %</strong>
              <small>sensitivitetsforutsetning</small>
            </div>
            <div>
              <span>Illustrativ årlig renteinntekt</span>
              <strong>R$ {formatNumber(interestProxyMbrl, 1)}m</strong>
              <small>cash × modellrente</small>
            </div>
            <div>
              <span>Otellos økonomiske look-through-andel</span>
              <strong>{moneyM(interestProxyOtecMnok)}</strong>
              <small>basert på eierandel, ikke utdelingsandel</small>
            </div>
          </div>
          <p className="cashNote">
            Renteinntekten er kun en sensitivitet på siste rapporterte cashbalanse. Faktisk renteinntekt avhenger av gjennomsnittlig cash gjennom perioden, CDI/Selic og plasseringstype.
          </p>
        </article>
      </section>

      <section className="card cashBuybackCard">
        <div className="cardHeader">
          <div>
            <span className="label">TILBAKEKJØPSKAPASITET</span>
            <h2>Hva kan Otello kjøpe tilbake – og hva gjør det med NAV?</h2>
          </div>
          <span className="pill">INTERAKTIV</span>
        </div>

        <div className={`cashBuybackConclusion ${buybackCalc?.limitingFactor === "PRICE" ? "warning" : ""}`}>
          <div>
            <span className="label">BEGRENSNING</span>
            <strong>{buybackConstraintTitle}</strong>
            <p>
              {buybackCalc?.limitingFactor === "MANDATE"
                ? `Med valgt cashnivå har Otello kapasitet til ${formatInteger(buybackCalc.financialCapacityShares)} aksjer, men dagens mandat har bare ${formatInteger(buybackCalc.remainingMandate)} aksjer igjen.`
                : buybackCalc?.limitingFactor === "PRICE"
                  ? `Valgt kjøpskurs på ${formatNumber(buybackCalc.price, 2)} kr er høyere enn programmets makspris på ${formatNumber(buyback?.program?.max_price_nok, 2)} kr. Kalkulatoren legger derfor til grunn null kjøp.`
                  : `Etter valgt minimumsnivå for cash kan Otello kjøpe inntil ${formatInteger(buybackCalc?.financialCapacityShares ?? null)} aksjer før kontantbufferen nås.`}
            </p>
          </div>
          <span className="pill cashConstraintPill">{buybackConstraintLabel}</span>
        </div>

        <div className="cashBuybackResults cashBuybackResultsPrimary">
          <div>
            <span>Gjenstående mandat</span>
            <strong>{formatInteger(buybackCalc?.remainingMandate ?? null)}</strong>
            <small>aksjer i dagens program</small>
          </div>
          <div>
            <span>Cash nødvendig</span>
            <strong>{moneyM(buybackCalc?.spendM)}</strong>
            <small>
              {buybackCalc == null
                ? "–"
                : `for ${formatInteger(buybackCalc.sharesBought)} aksjer ved ${formatNumber(buybackCalc.price, 2)} kr`}
            </small>
          </div>
          <div>
            <span>Cash etter kjøp</span>
            <strong>{moneyM(buybackCalc?.cashAfterM)}</strong>
            <small>valgt minimum {formatNumber(buybackCalc?.buffer ?? bufferM, 0)} mill. kr</small>
          </div>
          <div className={buybackCalc != null && buybackCalc.accretionPct >= 0 ? "cashAccretion positive" : "cashAccretion negative"}>
            <span>Økning i NAV per aksje</span>
            <strong>
              {buybackCalc == null
                ? "–"
                : `${buybackCalc.accretionPct >= 0 ? "+" : ""}${formatNumber(buybackCalc.accretionPct, 2)} %`}
            </strong>
            <small>
              {buybackCalc == null
                ? "–"
                : `${formatNumber(buybackCalc.navBeforePerShare, 2)} → ${formatNumber(buybackCalc.navAfterPerShare, 2)} kr`}
            </small>
          </div>
        </div>

        <div className="cashBuybackLayout cashBuybackLayoutSimplified">
          <div className="cashControls">
            <div className="cashBuybackSectionTitle">Forutsetninger</div>
            <label>
              <span><strong>Minimum cash Otello skal sitte igjen med</strong><em>{formatNumber(bufferM, 0)} mill. kr</em></span>
              <input
                type="range"
                min="0"
                max={maxBuffer}
                step="5"
                value={Math.min(bufferM, maxBuffer)}
                onChange={(event) => setBufferM(Number(event.target.value))}
              />
            </label>
            <label>
              <span><strong>Kjøpskurs OTEC</strong><em>{formatNumber(priceAssumption ?? summary.otec_price, 2)} kr</em></span>
              <input
                type="range"
                min="5"
                max={maxPrice}
                step="0.25"
                value={Math.min(Math.max(priceAssumption ?? summary.otec_price ?? 15, 5), maxPrice)}
                onChange={(event) => setPriceAssumption(Number(event.target.value))}
              />
            </label>
            <div className="cashAssumptionRows">
              <div><span>Dagens OTEC-kurs</span><strong>{formatNumber(summary.otec_price, 2)} kr</strong></div>
              <div><span>Programmets makspris</span><strong>{buyback?.program?.max_price_nok == null ? "–" : `${formatNumber(buyback.program.max_price_nok, 2)} kr`}</strong></div>
              <div><span>Allerede brukt på tilbakekjøp</span><strong>{moneyM(programSpentMnok)}</strong></div>
              <div><span>Teoretisk cashkapasitet</span><strong>{formatInteger(buybackCalc?.financialCapacityShares ?? null)} aksjer</strong></div>
            </div>
          </div>

          <div className="cashBuybackFlowCard">
            <div className="cashBuybackSectionTitle">Cashregnestykke</div>
            <div className="cashBuybackFlow">
              <div><span>Estimert OTEC-cash</span><strong>{moneyM(metrics.directCashM)}</strong></div>
              <div className="cashBuybackFlowMinus"><span>− Cash brukt på kjøpet</span><strong>{moneyM(buybackCalc?.spendM)}</strong></div>
              <div className="cashBuybackFlowTotal"><span>= Cash etter kjøp</span><strong>{moneyM(buybackCalc?.cashAfterM)}</strong></div>
            </div>
            <div className="cashBuybackSecondaryFacts">
              <div>
                <span>Over valgt minimum</span>
                <strong>{moneyM(buybackCalc?.cashAboveBufferM)}</strong>
              </div>
              <div>
                <span>Kjøpskurs mot NAV</span>
                <strong>
                  {buybackCalc == null
                    ? "–"
                    : `${formatNumber(buybackCalc.price, 2)} vs. ${formatNumber(buybackCalc.navBeforePerShare, 2)} kr`}
                </strong>
                <small>
                  {buybackCalc == null
                    ? "–"
                    : `${formatNumber(Math.abs(buybackCalc.discountToNavPct), 1)} % ${buybackCalc.discountToNavPct >= 0 ? "under NAV" : "over NAV"}`}
                </small>
              </div>
            </div>
          </div>
        </div>

        <p className="cashNote">
          Kalkulatoren viser hva som faktisk kan kjøpes innen både tilgjengelig cash, valgt minimumsnivå, programmets makspris og gjenstående mandat. NAV-effekten er en matematisk sensitivitetsanalyse, ikke en prognose for faktiske tilbakekjøp.
        </p>
      </section>

      <section className="card cashMethodCard">
        <div className="cardHeader">
          <div><span className="label">METODE</span><h2>Hva tallene betyr</h2></div>
        </div>
        <div className="cashMethodGrid">
          <div><strong>Direkte cash</strong><span>Samme estimerte kontantbeholdning og cash per aksje som på Oversikt, hentet fra den økonomiske cash-bridgen.</span></div>
          <div><strong>Look-through cash</strong><span>Otellos eierandel av Bemobis siste rapporterte cash, omregnet med siste BRL/NOK i tracker.</span></div>
          <div><strong>Utbyttemodell</strong><span>TTM-resultat × gjeldende payout-policy × Otellos distribusjonsandel, der hovedscenarioet antar ordinært utbytte og 10 % brasiliansk kildeskatt.</span></div>
          <div><strong>JCP-estimat</strong><span>JCP vises separat med 15 % kildeskatt som timing/form på deler av samme payout, og skal ikke dobbelttelles mot utbyttemodellen.</span></div>
        </div>
      </section>
    </div>
  );
}

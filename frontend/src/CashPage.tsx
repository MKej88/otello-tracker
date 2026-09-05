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
  estimated_cash_mnok?: number | null;
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
    payout_policy_pct?: number | null;
    policy_year?: number | null;
    estimated_total_distribution_mbrl?: number | null;
    otello_gross_mbrl?: number | null;
    otello_gross_mnok?: number | null;
    otello_gross_per_otec_share_nok?: number | null;
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
    const sharesBought = remainingMandate == null
      ? financialCapacityShares
      : Math.min(financialCapacityShares, Math.max(0, remainingMandate));
    const spendM = sharesBought * price / 1_000_000;
    const outstandingAfter = Math.max(1, shares - sharesBought);
    const navTotalM = navPerShare * shares / 1_000_000;
    const navAfterM = navTotalM - spendM;
    const navAfterPerShare = navAfterM * 1_000_000 / outstandingAfter;
    const accretionPct = (navAfterPerShare / navPerShare - 1) * 100;

    return {
      financialCapacityShares,
      sharesBought,
      spendM,
      navAfterPerShare,
      accretionPct,
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
    metrics.bemobiCashMbrl == null ? null : metrics.bemobiCashMbrl * 0.1425;
  const interestProxyOtecMnok =
    interestProxyMbrl == null || metrics.ownershipPct == null || metrics.brlNok == null
      ? null
      : interestProxyMbrl * metrics.ownershipPct / 100 * metrics.brlNok;
  const maxBuffer = Math.max(50, Math.ceil(metrics.directCashM ?? 50));
  const maxPrice = Math.max(30, Math.ceil((summary.otec_price ?? 15) * 1.8));
  const programSpent = finite(buyback?.program?.cash_spent_nok);
  const programSpentMnok = programSpent == null ? null : programSpent / 1_000_000;

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
              <span className="label">BEMOBI CASH ENGINE</span>
              <h2>Cash som kan fylle på Otello</h2>
            </div>
            <span className="pill">{bemobi.latest_result?.period ?? "SISTE KVARTAL"}</span>
          </div>
          <div className="cashMetricGrid">
            <div>
              <span>Bemobi cash</span>
              <strong>R$ {formatNumber(metrics.bemobiCashMbrl, 1)}m</strong>
              <small>{formatDate(bemobi.latest_result?.period_end)}</small>
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
            <div>
              <span>Netto cash</span>
              <strong>R$ {formatNumber(bemobi.valuation?.net_cash_mbrl, 1)}m</strong>
              <small>verdsettelsesanker</small>
            </div>
          </div>
          <div className="cashInterestStrip">
            <div>
              <span>Illustrativ renteinntekt ved 14,25 %</span>
              <strong>R$ {formatNumber(interestProxyMbrl, 1)}m</strong>
            </div>
            <div>
              <span>Otellos look-through-andel</span>
              <strong>{moneyM(interestProxyOtecMnok)}</strong>
            </div>
          </div>
          <p className="cashNote">
            Renteinntekten er kun en sensitivitetsillustrasjon på siste rapporterte cashbalanse, ikke et resultatestimat. Faktisk avkastning avhenger av gjennomsnittlig cash, CDI/Selic og plasseringstype.
          </p>
        </article>

        <article className="card cashDistributionCard">
          <div className="cardHeader">
            <div>
              <span className="label">CASH TIL OTEC</span>
              <h2>Forventet Bemobi-distribusjon</h2>
            </div>
            <span className="pill">{formatNumber(bemobi.distribution_estimate?.payout_policy_pct, 0)} % PAYOUT</span>
          </div>
          <div className="cashDistributionHeadline">
            <span>Otellos brutto run-rate</span>
            <strong>{moneyM(bemobi.distribution_estimate?.otello_gross_mnok)}</strong>
            <small>{formatNumber(bemobi.distribution_estimate?.otello_gross_per_otec_share_nok, 2)} kr per OTEC-aksje</small>
          </div>
          <div className="placeholderRows">
            <div><span>Bemobi distribuert run-rate</span><strong>R$ {formatNumber(bemobi.distribution_estimate?.estimated_total_distribution_mbrl, 1)}m</strong></div>
            <div><span>Otellos bruttoandel</span><strong>R$ {formatNumber(bemobi.distribution_estimate?.otello_gross_mbrl, 1)}m</strong></div>
            <div><span>Policy-år</span><strong>{bemobi.distribution_estimate?.policy_year ?? "–"}</strong></div>
          </div>
          <p className="cashNote">
            Dette er run-rate fra Bemobi-modellen. Faktisk kontantinnbetaling til Otello avhenger av vedtak, tidspunkt, JCP/utbytte-miks og kildeskatt.
          </p>
        </article>
      </section>

      <section className="card cashBuybackCard">
        <div className="cardHeader">
          <div>
            <span className="label">BUYBACK-KAPASITET</span>
            <h2>Hva skjer med NAV hvis cash brukes på egne aksjer?</h2>
          </div>
          <span className="pill">INTERAKTIV</span>
        </div>

        <div className="cashBuybackLayout">
          <div className="cashControls">
            <label>
              <span><strong>Minimum cash-buffer</strong><em>{formatNumber(bufferM, 0)} mill. kr</em></span>
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
              <div><span>Brukt i programmet</span><strong>{moneyM(programSpentMnok)}</strong></div>
              <div><span>Gjenstående programaksjer</span><strong>{formatInteger(buyback?.program?.remaining_shares ?? null)}</strong></div>
            </div>
          </div>

          <div className="cashBuybackResults">
            <div>
              <span>Finansiell kapasitet</span>
              <strong>{formatInteger(buybackCalc?.financialCapacityShares ?? null)}</strong>
              <small>aksjer før mandatbegrensning</small>
            </div>
            <div>
              <span>Innen dagens program</span>
              <strong>{formatInteger(buybackCalc?.sharesBought ?? null)}</strong>
              <small>aksjer</small>
            </div>
            <div>
              <span>Cash brukt</span>
              <strong>{moneyM(buybackCalc?.spendM)}</strong>
              <small>etter valgt buffer</small>
            </div>
            <div className={buybackCalc != null && buybackCalc.accretionPct >= 0 ? "cashAccretion positive" : "cashAccretion negative"}>
              <span>NAV-accretion</span>
              <strong>
                {buybackCalc == null
                  ? "–"
                  : `${buybackCalc.accretionPct >= 0 ? "+" : ""}${formatNumber(buybackCalc.accretionPct, 2)} %`}
              </strong>
              <small>ny NAV/aksje {buybackCalc == null ? "–" : `${formatNumber(buybackCalc.navAfterPerShare, 2)} kr`}</small>
            </div>
          </div>
        </div>
        <p className="cashNote">
          Kalkulatoren reduserer NAV med kontantbeløpet som brukes og aksjetallet med tilbakekjøpte aksjer. Når programdata er tilgjengelige begrenses kjøpet til gjenstående aksjer i dagens program. Dette er en matematisk sensitivitetsanalyse, ikke en prognose for faktisk tilbakekjøp.
        </p>
      </section>

      <section className="card cashMethodCard">
        <div className="cardHeader">
          <div><span className="label">METODE</span><h2>Hva tallene betyr</h2></div>
        </div>
        <div className="cashMethodGrid">
          <div><strong>Direkte cash</strong><span>Samme estimerte kontantbeholdning og cash per aksje som på Oversikt, hentet fra den økonomiske cash-bridgen.</span></div>
          <div><strong>Look-through cash</strong><span>Otellos eierandel av Bemobis siste rapporterte cash, omregnet med siste BRL/NOK i tracker.</span></div>
          <div><strong>Ikke dobbelttelling i NAV</strong><span>Look-through-cashen er en analyse av Bemobi-posten og skal ikke legges oppå NAV som en ny eiendel.</span></div>
          <div><strong>Datadatoer</strong><span>OTEC-cash oppdateres fra samme cash bridge som Oversikt. Bemobi-cash står på siste rapporterte kvartalsdato.</span></div>
        </div>
      </section>
    </div>
  );
}

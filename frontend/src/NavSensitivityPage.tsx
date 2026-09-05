import { useMemo, useState } from "react";

import { preloadJson } from "./navigationDataPreload";
import { usePollingResource } from "./usePollingResource";
import "./nav-sensitivity.css";

const REFRESH_MS = 2 * 60 * 1000;
const MILLION = 1_000_000;

type Summary = {
  ready: boolean;
  as_of_date?: string | null;
  otec_price?: number | null;
  bmob3_price?: number | null;
  brl_nok?: number | null;
  bemobi_shares?: number | null;
  bemobi_value_mnok?: number | null;
  bemobi_insights?: {
    price_brl?: number | null;
    holding_shares?: number | null;
    ownership_pct?: number | null;
  } | null;
  nav_discount_insights?: {
    nav_per_share?: number | null;
    share_price?: number | null;
    discount_pct?: number | null;
    upside_to_nav_pct?: number | null;
  } | null;
};

type EconomicNav = {
  ready: boolean;
  as_of_date?: string | null;
  calculated_at?: string | null;
  nav_total_mnok?: number | null;
  nav_per_share?: number | null;
  discount_pct?: number | null;
  shares_outstanding?: number | null;
  option?: {
    option_count?: number | null;
    strike_nok?: number | null;
    nav_before_option_per_share_nok?: number | null;
    nav_after_option_per_share_nok?: number | null;
    settlement_mnok?: number | null;
  } | null;
};

type DisplayMode = "nav" | "discount" | "upside" | "bemobi";

type Scenario = {
  bemobiPrice: number;
  brlNok: number;
  bemobiValueM: number;
  preOptionTotalM: number;
  navPerShare: number;
  optionSettlementM: number;
  discountPct: number | null;
  upsidePct: number | null;
};

type ScenarioInputs = {
  currentBemobiPrice: number;
  currentBrlNok: number;
  holdingShares: number;
  otecPrice: number;
  sharesOutstanding: number;
  optionCount: number;
  strikeNok: number;
  currentPreOptionTotalM: number;
  currentBemobiValueM: number;
};

const modeLabels: Array<{ key: DisplayMode; label: string }> = [
  { key: "nav", label: "NAV/aksje" },
  { key: "discount", label: "Rabatt" },
  { key: "upside", label: "Oppside" },
  { key: "bemobi", label: "Bemobi-post" },
];

export function preloadNavSensitivityData() {
  preloadJson("/api/dashboard/summary");
  preloadJson("/api/dashboard/economic");
}

function finite(value: number | null | undefined): value is number {
  return value != null && Number.isFinite(value);
}

function formatNumber(value: number | null | undefined, digits = 2) {
  if (!finite(value)) return "—";
  return value.toLocaleString("nb-NO", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function signedPercent(value: number | null | undefined, digits = 1) {
  if (!finite(value)) return "—";
  const prefix = value > 0 ? "+" : "";
  return `${prefix}${formatNumber(value, digits)} %`;
}

function dateLabel(input?: string | null) {
  if (!input) return "—";
  const [year, month, day] = input.slice(0, 10).split("-");
  return year && month && day ? `${day}.${month}.${year}` : input;
}

function buildSeries(current: number, count: number, step: number, minimum: number) {
  const center = Math.round(current / step) * step;
  const start = Math.max(minimum, center - Math.floor(count / 2) * step);
  return Array.from({ length: count }, (_, index) => Number((start + index * step).toFixed(4)));
}

function nearestIndex(values: number[], target: number) {
  return values.reduce((best, candidate, index) => (
    Math.abs(candidate - target) < Math.abs(values[best] - target) ? index : best
  ), 0);
}

function settlementNavPerShare(
  preOptionTotalM: number,
  sharesOutstanding: number,
  optionCount: number,
  strikeNok: number,
) {
  const preOptionTotalNok = preOptionTotalM * MILLION;
  const navBefore = preOptionTotalNok / sharesOutstanding;
  if (optionCount <= 0 || navBefore <= strikeNok) {
    return { navPerShare: navBefore, optionSettlementM: 0 };
  }

  const navAfter = (preOptionTotalNok + optionCount * strikeNok)
    / (sharesOutstanding + optionCount);
  const settlementPerOption = Math.max(0, navAfter - strikeNok);
  return {
    navPerShare: navAfter,
    optionSettlementM: optionCount * settlementPerOption / MILLION,
  };
}

function makeScenario(inputs: ScenarioInputs, bemobiPrice: number, brlNok: number): Scenario {
  const bemobiValueM = bemobiPrice * inputs.holdingShares * brlNok / MILLION;
  const preOptionTotalM = inputs.currentPreOptionTotalM
    + bemobiValueM
    - inputs.currentBemobiValueM;
  const settlement = settlementNavPerShare(
    preOptionTotalM,
    inputs.sharesOutstanding,
    inputs.optionCount,
    inputs.strikeNok,
  );
  const navPerShare = settlement.navPerShare;
  const discountPct = navPerShare > 0
    ? (1 - inputs.otecPrice / navPerShare) * 100
    : null;
  const upsidePct = inputs.otecPrice > 0
    ? (navPerShare / inputs.otecPrice - 1) * 100
    : null;

  return {
    bemobiPrice,
    brlNok,
    bemobiValueM,
    preOptionTotalM,
    navPerShare,
    optionSettlementM: settlement.optionSettlementM,
    discountPct,
    upsidePct,
  };
}

function solveMonotonicTarget(
  targetNav: number,
  navAt: (input: number) => number,
  initialHigh: number,
) {
  if (!Number.isFinite(targetNav) || targetNav <= 0) return null;
  let low = 0.0001;
  let high = Math.max(initialHigh, low * 2);
  const lowNav = navAt(low);
  if (!Number.isFinite(lowNav) || lowNav > targetNav) return null;

  let highNav = navAt(high);
  for (let attempt = 0; attempt < 16 && highNav < targetNav; attempt += 1) {
    high *= 2;
    highNav = navAt(high);
  }
  if (!Number.isFinite(highNav) || highNav < targetNav) return null;

  for (let iteration = 0; iteration < 70; iteration += 1) {
    const mid = (low + high) / 2;
    if (navAt(mid) < targetNav) low = mid;
    else high = mid;
  }
  return (low + high) / 2;
}

function scenarioTone(upsidePct: number | null) {
  if (!finite(upsidePct)) return "toneNeutral";
  if (upsidePct < 0) return "toneNegative";
  if (upsidePct < 10) return "toneFlat";
  if (upsidePct < 25) return "toneMild";
  if (upsidePct < 50) return "toneGood";
  return "toneStrong";
}

function modeValue(mode: DisplayMode, scenario: Scenario) {
  if (mode === "nav") return `${formatNumber(scenario.navPerShare)} kr`;
  if (mode === "discount") return finite(scenario.discountPct)
    ? `${formatNumber(scenario.discountPct, 1)} %`
    : "—";
  if (mode === "upside") return signedPercent(scenario.upsidePct);
  return `${formatNumber(scenario.bemobiValueM, 0)}m`;
}

export default function NavSensitivityPage() {
  const { data: summary, refreshFailed: summaryRefreshFailed } = usePollingResource<Summary>(
    "/api/dashboard/summary",
    REFRESH_MS,
    true,
  );
  const { data: economic, refreshFailed: economicRefreshFailed } = usePollingResource<EconomicNav>(
    "/api/dashboard/economic",
    REFRESH_MS,
    true,
  );
  const [mode, setMode] = useState<DisplayMode>("nav");
  const [selected, setSelected] = useState<{ bemobiPrice: number; brlNok: number } | null>(null);

  const inputs = useMemo<ScenarioInputs | null>(() => {
    const currentBemobiPrice = summary?.bemobi_insights?.price_brl ?? summary?.bmob3_price;
    const currentBrlNok = summary?.brl_nok;
    const holdingShares = summary?.bemobi_insights?.holding_shares ?? summary?.bemobi_shares;
    const otecPrice = summary?.otec_price ?? summary?.nav_discount_insights?.share_price;
    const sharesOutstanding = economic?.shares_outstanding;
    const optionCount = economic?.option?.option_count;
    const strikeNok = economic?.option?.strike_nok;
    const navBeforeOption = economic?.option?.nav_before_option_per_share_nok;

    if (
      !finite(currentBemobiPrice)
      || !finite(currentBrlNok)
      || !finite(holdingShares)
      || !finite(otecPrice)
      || !finite(sharesOutstanding)
      || !finite(optionCount)
      || !finite(strikeNok)
      || !finite(navBeforeOption)
      || currentBemobiPrice <= 0
      || currentBrlNok <= 0
      || holdingShares <= 0
      || otecPrice <= 0
      || sharesOutstanding <= 0
      || optionCount < 0
      || strikeNok < 0
    ) {
      return null;
    }

    return {
      currentBemobiPrice,
      currentBrlNok,
      holdingShares,
      otecPrice,
      sharesOutstanding,
      optionCount,
      strikeNok,
      currentPreOptionTotalM: navBeforeOption * sharesOutstanding / MILLION,
      currentBemobiValueM: currentBemobiPrice * holdingShares * currentBrlNok / MILLION,
    };
  }, [summary, economic]);

  const bemobiPrices = useMemo(
    () => inputs ? buildSeries(inputs.currentBemobiPrice, 9, 2.5, 2.5) : [],
    [inputs],
  );
  const brlRates = useMemo(
    () => inputs ? buildSeries(inputs.currentBrlNok, 7, 0.1, 0.1) : [],
    [inputs],
  );

  if (!inputs) {
    return (
      <div className="investorPage sensitivityPage">
        <section className="card sensitivityUnavailable">
          <span className="label">NAV-SENSITIVITET</span>
          <h2>Venter på komplett NAV-grunnlag</h2>
          <p>
            Siden trenger dagens Bemobi-kurs, BRL/NOK, Bemobi-beholdning, OTEC-kurs,
            aksjegrunnlag og opsjonsparametere for å bruke samme investor-NAV-logikk som resten av trackeren.
          </p>
        </section>
      </div>
    );
  }

  const nearestBemobi = nearestIndex(bemobiPrices, inputs.currentBemobiPrice);
  const nearestBrl = nearestIndex(brlRates, inputs.currentBrlNok);
  const selectedPoint = selected ?? {
    bemobiPrice: bemobiPrices[nearestBemobi],
    brlNok: brlRates[nearestBrl],
  };
  const selectedScenario = makeScenario(inputs, selectedPoint.bemobiPrice, selectedPoint.brlNok);
  const currentScenario = makeScenario(inputs, inputs.currentBemobiPrice, inputs.currentBrlNok);

  const breakEvenBemobi = solveMonotonicTarget(
    inputs.otecPrice,
    (price) => makeScenario(inputs, price, inputs.currentBrlNok).navPerShare,
    Math.max(50, inputs.currentBemobiPrice * 2),
  );
  const breakEvenBrl = solveMonotonicTarget(
    inputs.otecPrice,
    (fx) => makeScenario(inputs, inputs.currentBemobiPrice, fx).navPerShare,
    Math.max(4, inputs.currentBrlNok * 2),
  );
  const bemobiForThirtyPctUpside = solveMonotonicTarget(
    inputs.otecPrice * 1.3,
    (price) => makeScenario(inputs, price, inputs.currentBrlNok).navPerShare,
    Math.max(50, inputs.currentBemobiPrice * 2),
  );

  const fixedPreOptionM = inputs.currentPreOptionTotalM - inputs.currentBemobiValueM;
  const refreshFailed = summaryRefreshFailed || economicRefreshFailed;

  return (
    <div className="investorPage sensitivityPage">
      <section className="card sensitivityIntro">
        <div>
          <span className="label">NAV-SENSITIVITET</span>
          <h2>Hva er Otello verdt ved ulike Bemobi-kurser og BRL/NOK?</h2>
          <p>
            Kun Bemobi-kurs og BRL/NOK varierer. Øvrige NAV-komponenter holdes på dagens investor-NAV,
            mens kontant oppgjør av opsjonene beregnes på nytt i hvert scenario.
          </p>
        </div>
        <div className="sensitivityAsOf">
          <span>Datagrunnlag</span>
          <strong>{dateLabel(economic?.as_of_date ?? summary?.as_of_date)}</strong>
          <small>{refreshFailed ? "Viser siste gode data" : "Oppdateres automatisk"}</small>
        </div>
      </section>

      <section className="sensitivityKpis" aria-label="Dagens markedsverdier">
        <article className="card sensitivityKpi">
          <span>Bemobi</span>
          <strong>R$ {formatNumber(inputs.currentBemobiPrice)}</strong>
        </article>
        <article className="card sensitivityKpi">
          <span>BRL/NOK</span>
          <strong>{formatNumber(inputs.currentBrlNok, 4)}</strong>
        </article>
        <article className="card sensitivityKpi">
          <span>NAV</span>
          <strong>{formatNumber(economic?.nav_per_share ?? currentScenario.navPerShare)} kr</strong>
        </article>
        <article className="card sensitivityKpi">
          <span>OTEC</span>
          <strong>{formatNumber(inputs.otecPrice)} kr</strong>
        </article>
        <article className="card sensitivityKpi">
          <span>Oppside til NAV</span>
          <strong>{signedPercent(currentScenario.upsidePct)}</strong>
        </article>
      </section>

      <section className="card sensitivityMatrixCard">
        <div className="sensitivityMatrixHeader">
          <div>
            <span className="label">SCENARIOMATRISE</span>
            <h2>Bemobi × BRL/NOK</h2>
            <p>BRL/NOK betyr norske kroner per brasiliansk real.</p>
          </div>
          <div className="sensitivityModeButtons" aria-label="Velg hva matrisen skal vise">
            {modeLabels.map((item) => (
              <button
                className={mode === item.key ? "active" : ""}
                key={item.key}
                onClick={() => setMode(item.key)}
                type="button"
              >
                {item.label}
              </button>
            ))}
          </div>
        </div>

        <div className="sensitivityTableWrap">
          <table className="sensitivityTable">
            <thead>
              <tr>
                <th className="axisCorner">BRL/NOK ↓<br />Bemobi →</th>
                {bemobiPrices.map((price, priceIndex) => (
                  <th className={priceIndex === nearestBemobi ? "nearestAxis" : ""} key={price}>
                    R$ {formatNumber(price, 1)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {brlRates.map((fx, fxIndex) => (
                <tr key={fx}>
                  <th className={fxIndex === nearestBrl ? "nearestAxis" : ""}>{formatNumber(fx, 2)}</th>
                  {bemobiPrices.map((price, priceIndex) => {
                    const scenario = makeScenario(inputs, price, fx);
                    const isNearestMarket = priceIndex === nearestBemobi && fxIndex === nearestBrl;
                    const isSelected = selectedScenario.bemobiPrice === price && selectedScenario.brlNok === fx;
                    return (
                      <td key={`${fx}-${price}`}>
                        <button
                          aria-label={`Bemobi R$ ${formatNumber(price, 1)}, BRL/NOK ${formatNumber(fx, 2)}: ${modeValue(mode, scenario)}`}
                          className={`sensitivityCell ${scenarioTone(scenario.upsidePct)}${isSelected ? " selected" : ""}`}
                          onClick={() => setSelected({ bemobiPrice: price, brlNok: fx })}
                          type="button"
                        >
                          <strong>{modeValue(mode, scenario)}</strong>
                          {isNearestMarket && <small>Nå</small>}
                        </button>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="sensitivityLegend">
          <span className="toneNegative">NAV under OTEC</span>
          <span className="toneFlat">0–10 % oppside</span>
          <span className="toneMild">10–25 %</span>
          <span className="toneGood">25–50 %</span>
          <span className="toneStrong">50 %+</span>
        </div>
      </section>

      <section className="sensitivityDetailGrid">
        <article className="card sensitivityBreakEven">
          <div className="sensitivitySectionHeader">
            <div>
              <span className="label">HVA MÅ TIL?</span>
              <h2>Break-even og oppside</h2>
            </div>
          </div>
          <div className="breakEvenGrid">
            <div>
              <span>Bemobi for NAV = OTEC</span>
              <strong>{breakEvenBemobi == null ? "—" : `R$ ${formatNumber(breakEvenBemobi)}`}</strong>
              <small>ved dagens BRL/NOK</small>
            </div>
            <div>
              <span>BRL/NOK for NAV = OTEC</span>
              <strong>{breakEvenBrl == null ? "—" : formatNumber(breakEvenBrl, 4)}</strong>
              <small>ved dagens Bemobi-kurs</small>
            </div>
            <div>
              <span>Bemobi for +30 % oppside</span>
              <strong>{bemobiForThirtyPctUpside == null ? "—" : `R$ ${formatNumber(bemobiForThirtyPctUpside)}`}</strong>
              <small>ved dagens BRL/NOK</small>
            </div>
          </div>
        </article>

        <article className="card sensitivitySelected">
          <div className="sensitivitySectionHeader selectedHeader">
            <div>
              <span className="label">VALGT SCENARIO</span>
              <h2>R$ {formatNumber(selectedScenario.bemobiPrice, 1)} · BRL/NOK {formatNumber(selectedScenario.brlNok, 2)}</h2>
            </div>
            <button onClick={() => setSelected(null)} type="button">Tilbake til marked</button>
          </div>
          <div className="scenarioRows">
            <div><span>Bemobi-post</span><strong>{formatNumber(selectedScenario.bemobiValueM, 1)} mill. kr</strong></div>
            <div><span>Andre komponenter før opsjoner</span><strong>{formatNumber(fixedPreOptionM, 1)} mill. kr</strong></div>
            <div><span>Opsjonsoppgjør</span><strong>−{formatNumber(selectedScenario.optionSettlementM, 1)} mill. kr</strong></div>
            <div className="scenarioTotal"><span>NAV per OTEC-aksje</span><strong>{formatNumber(selectedScenario.navPerShare)} kr</strong></div>
            <div><span>Rabatt til NAV</span><strong>{finite(selectedScenario.discountPct) ? `${formatNumber(selectedScenario.discountPct, 1)} %` : "—"}</strong></div>
            <div><span>Oppside til NAV</span><strong>{signedPercent(selectedScenario.upsidePct)}</strong></div>
          </div>
        </article>
      </section>

      <p className="sensitivityMethodNote">
        Metode: scenarioet starter fra dagens investor-NAV før opsjonsoppgjør. Endringen i Bemobi-posten beregnes som
        Otellos Bemobi-aksjer × scenario-BMOB3 × scenario-BRL/NOK. Deretter brukes samme selvkonsistente kontantoppgjørslogikk
        for opsjonene som i investor-NAV. Alle øvrige komponenter holdes uendret.
      </p>
    </div>
  );
}

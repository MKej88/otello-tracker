import { useMemo, useState } from "react";

import { historicalScenarioRange } from "./sensitivityRange";

import { preloadJson } from "./navigationDataPreload";
import { usePollingResource } from "./usePollingResource";
import { usePageUpdate } from "./pageUpdateStatus";
import "./nav-sensitivity.css";

const REFRESH_MS = 2 * 60 * 1000;
const MILLION = 1_000_000;
const MAX_BEMOBI_POINTS = 15;
const MAX_BRL_POINTS = 12;

type Summary = {
  ready: boolean;
  as_of_date?: string | null;
  otec_price?: number | null;
  bmob3_price?: number | null;
  brl_nok?: number | null;
  bemobi_shares?: number | null;
  bemobi_value_mnok?: number | null;
  brl_nok_insights?: {
    range_1y?: { low?: number | null; high?: number | null } | null;
  } | null;
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

type MatrixRange = {
  bemobiFrom: number;
  bemobiTo: number;
  bemobiStep: number;
  brlFrom: number;
  brlTo: number;
  brlStep: number;
};

type MatrixRangeDraft = {
  bemobiFrom: string;
  bemobiTo: string;
  bemobiStep: string;
  brlFrom: string;
  brlTo: string;
  brlStep: string;
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

function inputNumber(value: number, digits: number) {
  return value.toFixed(digits).replace(/\.0+$/, "").replace(/(\.\d*?)0+$/, "$1");
}

function parsePositiveInput(value: string) {
  const parsed = Number(value.trim().replace(",", "."));
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
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

function buildRange(from: number, to: number, step: number, maxPoints: number) {
  if (![from, to, step].every((value) => Number.isFinite(value) && value > 0)) return [];
  if (to < from || step <= 0) return [];
  const pointCount = Math.floor((to - from) / step + 1e-9) + 1;
  if (pointCount < 2 || pointCount > maxPoints) return [];
  return Array.from({ length: pointCount }, (_, index) => Number((from + index * step).toFixed(4)));
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
  usePageUpdate(economic?.calculated_at ?? economic?.as_of_date ?? summary?.as_of_date, "intraday");
  const [mode, setMode] = useState<DisplayMode>("nav");
  const [selected, setSelected] = useState<{ bemobiPrice: number; brlNok: number } | null>(null);
  const [rangeEditorOpen, setRangeEditorOpen] = useState(false);
  const [customRange, setCustomRange] = useState<MatrixRange | null>(null);
  const [rangeDraft, setRangeDraft] = useState<MatrixRangeDraft | null>(null);
  const [rangeError, setRangeError] = useState<string | null>(null);

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

  const autoBemobiPrices = useMemo(
    () => inputs ? buildSeries(inputs.currentBemobiPrice, 9, 2.5, 2.5) : [],
    [inputs],
  );
  const historicalBrlRates = useMemo(
    () => inputs ? historicalScenarioRange(
      summary?.brl_nok_insights?.range_1y?.low,
      summary?.brl_nok_insights?.range_1y?.high,
      inputs.currentBrlNok,
      7,
    ) : [],
    [inputs, summary],
  );
  const autoBrlRates = useMemo(
    () => historicalBrlRates.length ? historicalBrlRates
      : inputs ? buildSeries(inputs.currentBrlNok, 7, 0.1, 0.1) : [],
    [inputs, historicalBrlRates],
  );
  const bemobiPrices = useMemo(
    () => customRange
      ? buildRange(customRange.bemobiFrom, customRange.bemobiTo, customRange.bemobiStep, MAX_BEMOBI_POINTS)
      : autoBemobiPrices,
    [customRange, autoBemobiPrices],
  );
  const brlRates = useMemo(
    () => customRange
      ? buildRange(customRange.brlFrom, customRange.brlTo, customRange.brlStep, MAX_BRL_POINTS)
      : autoBrlRates,
    [customRange, autoBrlRates],
  );

  if (!inputs || bemobiPrices.length === 0 || brlRates.length === 0) {
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
  const marketBemobiInRange = inputs.currentBemobiPrice >= bemobiPrices[0]
    && inputs.currentBemobiPrice <= bemobiPrices[bemobiPrices.length - 1];
  const marketBrlInRange = inputs.currentBrlNok >= brlRates[0]
    && inputs.currentBrlNok <= brlRates[brlRates.length - 1];
  const selectedPoint = selected ?? {
    bemobiPrice: bemobiPrices[nearestBemobi],
    brlNok: brlRates[nearestBrl],
  };
  const selectedScenario = makeScenario(inputs, selectedPoint.bemobiPrice, selectedPoint.brlNok);
  const currentScenario = makeScenario(inputs, inputs.currentBemobiPrice, inputs.currentBrlNok);

  const fixedPreOptionM = inputs.currentPreOptionTotalM - inputs.currentBemobiValueM;
  const refreshFailed = summaryRefreshFailed || economicRefreshFailed;

  function openRangeEditor() {
    const bemobiStep = customRange?.bemobiStep ?? (bemobiPrices[1] - bemobiPrices[0]);
    const brlStep = customRange?.brlStep ?? (brlRates[1] - brlRates[0]);
    setRangeDraft({
      bemobiFrom: inputNumber(bemobiPrices[0], 2),
      bemobiTo: inputNumber(bemobiPrices[bemobiPrices.length - 1], 2),
      bemobiStep: inputNumber(bemobiStep, 2),
      brlFrom: inputNumber(brlRates[0], 4),
      brlTo: inputNumber(brlRates[brlRates.length - 1], 4),
      brlStep: inputNumber(brlStep, 4),
    });
    setRangeError(null);
    setRangeEditorOpen(true);
  }

  function applyRange() {
    if (!rangeDraft) return;
    const nextRange = {
      bemobiFrom: parsePositiveInput(rangeDraft.bemobiFrom),
      bemobiTo: parsePositiveInput(rangeDraft.bemobiTo),
      bemobiStep: parsePositiveInput(rangeDraft.bemobiStep),
      brlFrom: parsePositiveInput(rangeDraft.brlFrom),
      brlTo: parsePositiveInput(rangeDraft.brlTo),
      brlStep: parsePositiveInput(rangeDraft.brlStep),
    };
    if (Object.values(nextRange).some((value) => value == null)) {
      setRangeError("Alle feltene må inneholde positive tall.");
      return;
    }

    const validRange = nextRange as MatrixRange;
    const nextBemobi = buildRange(
      validRange.bemobiFrom,
      validRange.bemobiTo,
      validRange.bemobiStep,
      MAX_BEMOBI_POINTS,
    );
    const nextBrl = buildRange(validRange.brlFrom, validRange.brlTo, validRange.brlStep, MAX_BRL_POINTS);
    if (validRange.bemobiTo <= validRange.bemobiFrom || validRange.brlTo <= validRange.brlFrom) {
      setRangeError("Til-verdi må være høyere enn fra-verdi.");
      return;
    }
    if (nextBemobi.length < 2 || nextBrl.length < 2) {
      setRangeError(`Velg minst 2 punkter og maks ${MAX_BEMOBI_POINTS} Bemobi-kolonner / ${MAX_BRL_POINTS} BRL-rader.`);
      return;
    }

    setCustomRange(validRange);
    setSelected(null);
    setRangeEditorOpen(false);
    setRangeError(null);
  }

  function resetRange() {
    setCustomRange(null);
    setSelected(null);
    setRangeEditorOpen(false);
    setRangeError(null);
  }

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
            {!customRange && <p>{historicalBrlRates.length
              ? "BRL/NOK-intervallet følger automatisk siste 52 ukers laveste og høyeste kurs."
              : "52-ukersintervallet for BRL/NOK mangler. Viser foreløpig et intervall rundt dagens kurs."}</p>}
          </div>
          <div className="sensitivityMatrixActions">
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
            <div className="sensitivityRangeActions">
              <button onClick={openRangeEditor} type="button">
                {customRange ? "Endre intervaller" : "Tilpass intervaller"}
              </button>
              {customRange && <button className="secondary" onClick={resetRange} type="button">Standardintervall</button>}
            </div>
          </div>
        </div>

        {rangeEditorOpen && rangeDraft && (
          <form className="sensitivityRangeEditor" onSubmit={(event) => { event.preventDefault(); applyRange(); }}>
            <div className="rangeEditorLead">
              <div>
                <strong>Egendefinerte intervaller</strong>
                <small>Maks {MAX_BEMOBI_POINTS} Bemobi-kolonner og {MAX_BRL_POINTS} BRL-rader.</small>
              </div>
              <button className="rangeClose" onClick={() => { setRangeEditorOpen(false); setRangeError(null); }} type="button">Lukk</button>
            </div>
            <div className="rangeEditorGroups">
              <fieldset>
                <legend>Bemobi (R$)</legend>
                <label>Fra<input inputMode="decimal" min="0.01" step="any" value={rangeDraft.bemobiFrom} onChange={(event) => setRangeDraft({ ...rangeDraft, bemobiFrom: event.target.value })} /></label>
                <label>Til<input inputMode="decimal" min="0.01" step="any" value={rangeDraft.bemobiTo} onChange={(event) => setRangeDraft({ ...rangeDraft, bemobiTo: event.target.value })} /></label>
                <label>Steg<input inputMode="decimal" min="0.01" step="any" value={rangeDraft.bemobiStep} onChange={(event) => setRangeDraft({ ...rangeDraft, bemobiStep: event.target.value })} /></label>
              </fieldset>
              <fieldset>
                <legend>BRL/NOK</legend>
                <label>Fra<input inputMode="decimal" min="0.01" step="any" value={rangeDraft.brlFrom} onChange={(event) => setRangeDraft({ ...rangeDraft, brlFrom: event.target.value })} /></label>
                <label>Til<input inputMode="decimal" min="0.01" step="any" value={rangeDraft.brlTo} onChange={(event) => setRangeDraft({ ...rangeDraft, brlTo: event.target.value })} /></label>
                <label>Steg<input inputMode="decimal" min="0.001" step="any" value={rangeDraft.brlStep} onChange={(event) => setRangeDraft({ ...rangeDraft, brlStep: event.target.value })} /></label>
              </fieldset>
            </div>
            {rangeError && <p className="rangeError" role="alert">{rangeError}</p>}
            <div className="rangeEditorButtons">
              <button className="primary" type="submit">Bruk intervaller</button>
              <button onClick={resetRange} type="button">Tilbakestill standardintervall</button>
            </div>
          </form>
        )}

        <div className="sensitivityTableWrap">
          <table className="sensitivityTable" style={{ minWidth: `${Math.max(900, 110 + bemobiPrices.length * 95)}px` }}>
            <thead>
              <tr>
                <th className="axisCorner">BRL/NOK ↓<br />Bemobi →</th>
                {bemobiPrices.map((price, priceIndex) => (
                  <th className={marketBemobiInRange && priceIndex === nearestBemobi ? "nearestAxis" : ""} key={price}>
                    R$ {formatNumber(price, 1)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {brlRates.map((fx, fxIndex) => (
                <tr key={fx}>
                  <th className={marketBrlInRange && fxIndex === nearestBrl ? "nearestAxis" : ""}>{formatNumber(fx, 4)}</th>
                  {bemobiPrices.map((price, priceIndex) => {
                    const scenario = makeScenario(inputs, price, fx);
                    const isNearestMarket = marketBemobiInRange
                      && marketBrlInRange
                      && priceIndex === nearestBemobi
                      && fxIndex === nearestBrl;
                    const isSelected = selectedScenario.bemobiPrice === price && selectedScenario.brlNok === fx;
                    return (
                      <td key={`${fx}-${price}`}>
                        <button
                          aria-label={`Bemobi R$ ${formatNumber(price, 1)}, BRL/NOK ${formatNumber(fx, 4)}: ${modeValue(mode, scenario)}`}
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
        <article className="card sensitivitySelected">
          <div className="sensitivitySectionHeader selectedHeader">
            <div>
              <span className="label">VALGT SCENARIO</span>
              <h2>R$ {formatNumber(selectedScenario.bemobiPrice, 1)} · BRL/NOK {formatNumber(selectedScenario.brlNok, 4)}</h2>
            </div>
            <button onClick={() => setSelected(null)} type="button">Tilbake til matrise</button>
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

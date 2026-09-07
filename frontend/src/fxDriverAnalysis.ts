export type CurrencyDirection = "sterkere" | "svakere" | "uendret";
export type MainDriver = "NOK" | "BRL" | null;

export type FxDriverAnalysis = {
  totalPct: number;
  nokContribution: number;
  brlContribution: number;
  nokDirection: CurrencyDirection;
  brlDirection: CurrencyDirection;
  mainDriver: MainDriver;
  explanation: string;
};

const EPSILON = 0.000_001;

function direction(changeAgainstUsd: number): CurrencyDirection {
  if (Math.abs(changeAgainstUsd) < EPSILON) return "uendret";
  return changeAgainstUsd < 0 ? "sterkere" : "svakere";
}

function mainDriver(
  nokContribution: number,
  brlContribution: number,
): MainDriver {
  const nokSize = Math.abs(nokContribution);
  const brlSize = Math.abs(brlContribution);
  const largest = Math.max(nokSize, brlSize);
  if (largest < EPSILON) return null;

  // Små forskjeller bør ikke fremstilles som en sikker konklusjon.
  const approximatelyEqual = Math.abs(nokSize - brlSize)
    <= Math.max(0.1, largest * 0.15);
  if (approximatelyEqual) return null;
  return nokSize > brlSize ? "NOK" : "BRL";
}

function driverExplanation(
  driver: MainDriver,
  nokDirection: CurrencyDirection,
  brlDirection: CurrencyDirection,
): string {
  if (!driver) {
    return "Ingen tydelig hoveddriver – NOK og BRL har bidratt omtrent like mye.";
  }

  const driverName = driver === "NOK" ? "Den norske kronen" : "Den brasilianske realen";
  const driverDirection = driver === "NOK" ? nokDirection : brlDirection;
  const result = driver === "NOK"
    ? nokDirection === "sterkere"
      ? "Dermed får hver BRL lavere verdi målt i NOK."
      : "Dermed får hver BRL høyere verdi målt i NOK."
    : brlDirection === "sterkere"
      ? "Dermed får hver BRL høyere verdi målt i NOK."
      : "Dermed får hver BRL lavere verdi målt i NOK.";

  return `${driverName} har vært viktigst og er ${driverDirection} mot USD. ${result}`;
}

/**
 * Fordeler den eksakte endringen i (USD/NOK) / (USD/BRL) symmetrisk mellom
 * valutaene. Shapley-fordelingen deler samspillet likt og summerer alltid til
 * den matematisk korrekte krysskursendringen.
 */
export function analyzeFxDrivers(
  usdNokPct: number,
  usdBrlPct: number,
): FxDriverAnalysis | null {
  if (!Number.isFinite(usdNokPct) || !Number.isFinite(usdBrlPct)) return null;

  const nokMove = usdNokPct / 100;
  const brlMove = usdBrlPct / 100;
  if (1 + brlMove <= 0) return null;

  const onlyNok = nokMove;
  const onlyBrl = 1 / (1 + brlMove) - 1;
  const total = (1 + nokMove) / (1 + brlMove) - 1;
  const nokContribution = (onlyNok + total - onlyBrl) / 2 * 100;
  const brlContribution = (onlyBrl + total - onlyNok) / 2 * 100;
  const nokDirection = direction(usdNokPct);
  const brlDirection = direction(usdBrlPct);
  const driver = mainDriver(nokContribution, brlContribution);

  return {
    totalPct: total * 100,
    nokContribution,
    brlContribution,
    nokDirection,
    brlDirection,
    mainDriver: driver,
    explanation: driverExplanation(driver, nokDirection, brlDirection),
  };
}

export function movementText(
  currency: "NOK" | "BRL",
  directionValue: CurrencyDirection,
  changeAgainstUsd: number,
  formatMagnitude: (value: number) => string,
): string {
  if (directionValue === "uendret") return `${currency} var uendret mot USD`;
  const verb = directionValue === "sterkere" ? "styrket" : "svekket";
  return `${currency} ${verb} seg ${formatMagnitude(Math.abs(changeAgainstUsd))} mot USD`;
}

export function roundedContributions(
  analysis: FxDriverAnalysis,
  digits = 1,
): { nok: number; brl: number; total: number } {
  const factor = 10 ** digits;
  const rounded = (value: number) => Math.round((value + Number.EPSILON) * factor) / factor;
  const total = rounded(analysis.totalPct);
  const nok = rounded(analysis.nokContribution);
  const brl = rounded(total - nok);
  return {
    nok: Object.is(nok, -0) ? 0 : nok,
    brl: Object.is(brl, -0) ? 0 : brl,
    total: Object.is(total, -0) ? 0 : total,
  };
}

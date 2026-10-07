export function medianDiscountPriceLine(
  nav: number | null | undefined,
  medianDiscountPct: number | null | undefined,
  otecPrice: number | null | undefined,
  formatNumber: (value: number, digits: number) => string,
): string | null {
  if (nav == null || !Number.isFinite(nav) || nav <= 0
    || medianDiscountPct == null || !Number.isFinite(medianDiscountPct)
    || otecPrice == null || !Number.isFinite(otecPrice) || otecPrice <= 0) return null;

  // The history API supplies percentage points (22.8), not a fraction (0.228).
  const price = nav * (1 - medianDiscountPct / 100);
  const upsidePct = (price / otecPrice - 1) * 100;
  if (!Number.isFinite(price) || price < 0 || !Number.isFinite(upsidePct)) return null;

  // Apply the sign after rounding so small changes never display +0.0 or −0.0.
  const magnitude = Math.round(Math.abs(upsidePct) * 10) / 10;
  const sign = magnitude === 0 ? "" : upsidePct > 0 ? "+" : "−";
  return `Ved 1-års medianrabatt (${formatNumber(medianDiscountPct, 1)} %): ${formatNumber(price, 2)} kr (${sign}${formatNumber(magnitude, 1)} %)`;
}

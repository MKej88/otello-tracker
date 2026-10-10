export function navUpsideLine(
  nav: number | null | undefined,
  otecPrice: number | null | undefined,
  formatNumber: (value: number, digits: number) => string,
): string | null {
  if (nav == null || !Number.isFinite(nav) || nav <= 0
    || otecPrice == null || !Number.isFinite(otecPrice) || otecPrice <= 0) return null;

  const perShare = nav - otecPrice;
  const percent = (nav / otecPrice - 1) * 100;
  if (!Number.isFinite(perShare) || !Number.isFinite(percent)) return null;

  const signed = (value: number, digits: number) => {
    const scale = 10 ** digits;
    const magnitude = Math.round(Math.abs(value) * scale) / scale;
    const sign = magnitude === 0 ? "" : value > 0 ? "+" : "−";
    return `${sign}${formatNumber(magnitude, digits)}`;
  };
  return `${signed(perShare, 2)} kr (${signed(percent, 1)} %)`;
}

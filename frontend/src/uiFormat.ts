const NUMBER_LOCALE = "nb-NO";
const numberFormatters = new Map<number, Intl.NumberFormat>();

export function formatNumber(input: number | null | undefined, digits = 2): string {
  if (input == null || !Number.isFinite(input)) return "–";
  let formatter = numberFormatters.get(digits);
  if (!formatter) {
    formatter = new Intl.NumberFormat(NUMBER_LOCALE, {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
    numberFormatters.set(digits, formatter);
  }
  return formatter.format(input);
}

export function formatInteger(input: number | null | undefined): string {
  if (input == null || !Number.isFinite(input)) return "–";
  return Math.round(input).toLocaleString(NUMBER_LOCALE);
}

export function formatDate(input?: string | null): string {
  if (!input) return "–";
  const [year, month, day] = input.slice(0, 10).split("-");
  return year && month && day ? `${day}.${month}.${year}` : input;
}

export function formatDateTime(
  input?: string | Date | null,
): string {
  if (!input) return "–";
  const parsed = input instanceof Date ? input : new Date(input);
  if (!Number.isFinite(parsed.getTime())) return String(input);
  const date = parsed.toLocaleDateString(NUMBER_LOCALE, {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    timeZone: "Europe/Oslo",
  });
  const time = parsed.toLocaleTimeString(NUMBER_LOCALE, {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Europe/Oslo",
  });
  return `${date} kl. ${time}`;
}

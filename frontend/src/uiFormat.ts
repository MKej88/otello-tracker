const NUMBER_LOCALE = "nb-NO";
const numberFormatters = new Map<number, Intl.NumberFormat>();
const dateTimeFormatters = new Map<string, Intl.DateTimeFormat>();

/** Reuse locale formatters across renders; construct lazily on first use. */
export function cachedDateTimeFormatter(locale: string, options: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
  const key = JSON.stringify([locale, options]);
  let formatter = dateTimeFormatters.get(key);
  if (!formatter) {
    formatter = new Intl.DateTimeFormat(locale, options);
    dateTimeFormatters.set(key, formatter);
  }
  return formatter;
}

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
  return formatNumber(Math.round(input), 0);
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
  const date = cachedDateTimeFormatter(NUMBER_LOCALE, {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    timeZone: "Europe/Oslo",
  }).format(parsed);
  const time = cachedDateTimeFormatter(NUMBER_LOCALE, {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Europe/Oslo",
  }).format(parsed);
  return `${date} kl. ${time}`;
}


// Keep legacy cached API responses consistent with the current Norwegian calendar.
export function formatCompanyEventTitle(title: string, company: string): string {
  if (company !== "Bemobi") return title;
  if (title === "Betalingsdato for JCP") return "Utbetaling av renter på egenkapital";
  if (title === "Ex-dato for JCP") return "Ex-dato for renter på egenkapital";
  return title;
}

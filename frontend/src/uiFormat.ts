const NUMBER_LOCALE = "nb-NO";

export function formatNumber(input: number | null | undefined, digits = 2): string {
  if (input == null || !Number.isFinite(input)) return "–";
  return input.toLocaleString(NUMBER_LOCALE, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
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
  input?: string | null,
  includeYear = true,
): string {
  if (!input) return "–";
  const parsed = new Date(input);
  if (!Number.isFinite(parsed.getTime())) return input;
  return parsed.toLocaleString(NUMBER_LOCALE, {
    day: "2-digit",
    month: "2-digit",
    ...(includeYear ? { year: "numeric" } : {}),
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Europe/Oslo",
  });
}

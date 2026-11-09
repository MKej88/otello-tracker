/**
 * Expected weekly Focus publication dates, based on the preceding Friday's survey.
 * These are scheduled dates, not confirmation that BCB has released a report.
 * BCB normally publishes on Monday and moves releases past Brazilian bank holidays.
 */
export type FocusPublicationDates = {
  publishedDate: string | null;
  nextExpectedDate: string | null;
};

function parseIsoDate(value?: string | null): Date | null {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const parsed = new Date(`${value}T00:00:00Z`);
  return Number.isNaN(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== value ? null : parsed;
}

function addDays(value: Date, days: number): Date {
  const shifted = new Date(value);
  shifted.setUTCDate(shifted.getUTCDate() + days);
  return shifted;
}

function isoDate(value: Date): string {
  return value.toISOString().slice(0, 10);
}

function easterSunday(year: number): Date {
  // Gregorian computus; only used for movable Brazilian bank holidays.
  const a = year % 19, b = Math.floor(year / 100), c = year % 100;
  const d = Math.floor(b / 4), e = b % 4, f = Math.floor((b + 8) / 25);
  const g = Math.floor((b - f + 1) / 3), h = (19 * a + b - d - g + 15) % 30;
  const i = Math.floor(c / 4), k = c % 4, l = (32 + 2 * e + 2 * i - h - k) % 7;
  const m = Math.floor((a + 11 * h + 22 * l) / 451);
  const month = Math.floor((h + l - 7 * m + 114) / 31);
  const day = ((h + l - 7 * m + 114) % 31) + 1;
  return new Date(Date.UTC(year, month - 1, day));
}

function isBrazilBankHoliday(value: Date): boolean {
  const fixedHolidays = new Set([
    "01-01", "04-21", "05-01", "09-07", "10-12", "11-02",
    "11-15", "11-20", "12-25",
  ]);
  const monthDay = isoDate(value).slice(5);
  if (fixedHolidays.has(monthDay)) return true;
  const easter = easterSunday(value.getUTCFullYear()).getTime();
  const offset = Math.round((value.getTime() - easter) / 86_400_000);
  // Carnival Monday/Tuesday, Ash Wednesday, Good Friday and Corpus Christi.
  return [-48, -47, -46, -2, 60].includes(offset);
}

function nextBusinessDay(value: Date): Date {
  let date = value;
  while (date.getUTCDay() === 0 || date.getUTCDay() === 6 || isBrazilBankHoliday(date)) {
    date = addDays(date, 1);
  }
  return date;
}

export function focusPublicationDates(referenceDate?: string | null, asOfDate?: string | null): FocusPublicationDates {
  const reference = parseIsoDate(referenceDate);
  const asOf = parseIsoDate(asOfDate);
  if (!reference || !asOf) return { publishedDate: null, nextExpectedDate: null };

  // Friday on or after the survey date, then the normally following Monday.
  // Aligning non-Friday live survey dates forward avoids claiming premature publication.
  const daysToFriday = (5 - reference.getUTCDay() + 7) % 7;
  const firstMonday = addDays(reference, daysToFriday + 3);
  const release = nextBusinessDay(firstMonday);

  // If the scheduled release is today, do not label it "published" before BCB
  // has confirmed publication. The next expected date remains the same day.
  if (release.getTime() >= asOf.getTime()) {
    return { publishedDate: null, nextExpectedDate: isoDate(release) };
  }

  let nextMonday = addDays(firstMonday, 7);
  let nextRelease = nextBusinessDay(nextMonday);
  while (nextRelease.getTime() < asOf.getTime()) {
    nextMonday = addDays(nextMonday, 7);
    nextRelease = nextBusinessDay(nextMonday);
  }
  return { publishedDate: isoDate(release), nextExpectedDate: isoDate(nextRelease) };
}

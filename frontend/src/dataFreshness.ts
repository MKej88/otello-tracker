export type FreshnessCadence = "intraday" | "daily";
export type FreshnessStatus = "fresh" | "delayed" | "stale" | "unavailable";

const MINUTE_MS = 60_000;
const OSLO_TIME_ZONE = "Europe/Oslo";

function validDate(value?: string | null): Date | null {
  if (!value) return null;
  const parsed = new Date(value);
  return Number.isFinite(parsed.getTime()) ? parsed : null;
}

function osloParts(value: Date) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: OSLO_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    hourCycle: "h23",
  }).formatToParts(value);
  const number = (type: Intl.DateTimeFormatPartTypes) =>
    Number(parts.find((part) => part.type === type)?.value);
  return {
    year: number("year"),
    month: number("month"),
    day: number("day"),
    hour: number("hour"),
  };
}

function businessDaysOld(observed: Date, now: Date): number {
  const observedParts = osloParts(observed);
  const nowParts = osloParts(now);
  const cursor = new Date(
    Date.UTC(observedParts.year, observedParts.month - 1, observedParts.day),
  );
  const end = new Date(Date.UTC(nowParts.year, nowParts.month - 1, nowParts.day));
  let days = 0;
  while (cursor < end) {
    cursor.setUTCDate(cursor.getUTCDate() + 1);
    if (cursor.getUTCDay() !== 0 && cursor.getUTCDay() !== 6) days += 1;
  }
  return days;
}

export function freshnessStatus(
  cadence: FreshnessCadence,
  timestamp?: string | null,
  now = new Date(),
): FreshnessStatus {
  const observed = validDate(timestamp);
  if (!observed) return "unavailable";
  const ageMinutes = (now.getTime() - observed.getTime()) / MINUTE_MS;
  if (ageMinutes < 0) return "unavailable";

  const businessAge = businessDaysOld(observed, now);
  if (cadence === "daily") {
    if (businessAge <= 1) return "fresh";
    if (businessAge <= 2) return "delayed";
    return "stale";
  }

  // Intradagspanelet blander Oslo-, Brasil- og USA-markeder. Før de utenlandske
  // børsene normalt har rukket å åpne, er gårsdagens sluttkurs forventet og skal
  // derfor ikke vises som en rød feil. Vi bruker et konservativt felles vindu
  // fra kl. 16 norsk/lokal tid for å avgjøre om en gammel intradagverdi faktisk
  // burde ha vært oppdatert. Ferske beregnede verdier (f.eks. NAV) forblir grønne.
  if (ageMinutes <= 60) return "fresh";

  const nowParts = osloParts(now);
  const osloDay = new Date(
    Date.UTC(nowParts.year, nowParts.month - 1, nowParts.day),
  ).getUTCDay();
  const weekday = osloDay !== 0 && osloDay !== 6;
  const hour = nowParts.hour;
  const strictIntradayWindow = weekday && hour >= 16 && hour < 22;
  if (strictIntradayWindow) {
    if (ageMinutes <= 6 * 60) return "delayed";
    return "stale";
  }

  if (businessAge <= 1) return "delayed";
  return "stale";
}

export function freshnessTimestamp(value?: string | null, now = new Date()): string {
  const parsed = validDate(value);
  if (!parsed) return "—";
  const dateOptions = { timeZone: OSLO_TIME_ZONE };
  const sameDay = parsed.toLocaleDateString("nb-NO", dateOptions)
    === now.toLocaleDateString("nb-NO", dateOptions);
  const time = parsed.toLocaleTimeString("nb-NO", {
    timeZone: OSLO_TIME_ZONE,
    hour: "2-digit",
    minute: "2-digit",
  });
  if (sameDay) return time;
  const date = parsed.toLocaleDateString("nb-NO", {
    timeZone: OSLO_TIME_ZONE,
    day: "2-digit",
    month: "2-digit",
  });
  return `${date} · ${time}`;
}

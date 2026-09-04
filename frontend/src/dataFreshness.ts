export type FreshnessCadence = "intraday" | "daily";
export type FreshnessStatus = "fresh" | "delayed" | "stale" | "unavailable";

const MINUTE_MS = 60_000;

function validDate(value?: string | null): Date | null {
  if (!value) return null;
  const parsed = new Date(value);
  return Number.isFinite(parsed.getTime()) ? parsed : null;
}

function businessDaysOld(observed: Date, now: Date): number {
  const cursor = new Date(observed.getFullYear(), observed.getMonth(), observed.getDate());
  const end = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  let days = 0;
  while (cursor < end) {
    cursor.setDate(cursor.getDate() + 1);
    if (cursor.getDay() !== 0 && cursor.getDay() !== 6) days += 1;
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

  const weekday = now.getDay() !== 0 && now.getDay() !== 6;
  const hour = now.getHours();
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
  const sameDay = parsed.toLocaleDateString("nb-NO") === now.toLocaleDateString("nb-NO");
  const time = parsed.toLocaleTimeString("nb-NO", { hour: "2-digit", minute: "2-digit" });
  if (sameDay) return time;
  const date = parsed.toLocaleDateString("nb-NO", { day: "2-digit", month: "2-digit" });
  return `${date} · ${time}`;
}


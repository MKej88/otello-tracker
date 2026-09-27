const OSLO_TIME_ZONE = "Europe/Oslo";

function osloDateKey(date: Date) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: OSLO_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(date);
  const value = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((part) => part.type === type)?.value;
  return `${value("year")}-${value("month")}-${value("day")}`;
}

function previousDateKey(dateKey: string) {
  const date = new Date(`${dateKey}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() - 1);
  return date.toISOString().slice(0, 10);
}

export function pageUpdateLabel(timestamp?: string | null, now = new Date()) {
  if (!timestamp) return "Oppdateringstidspunkt mangler";
  const parsed = new Date(timestamp);
  if (!Number.isFinite(parsed.getTime())) return "Oppdateringstidspunkt mangler";

  const observedKey = /^\d{4}-\d{2}-\d{2}$/.test(timestamp)
    ? timestamp
    : osloDateKey(parsed);
  const todayKey = osloDateKey(now);
  const hasTime = !/^\d{4}-\d{2}-\d{2}$/.test(timestamp);
  const time = hasTime
    ? ` kl. ${new Intl.DateTimeFormat("nb-NO", {
        timeZone: OSLO_TIME_ZONE,
        hour: "2-digit",
        minute: "2-digit",
      }).format(parsed)}`
    : "";

  if (observedKey === todayKey) return `Oppdatert i dag${time}`;
  if (observedKey === previousDateKey(todayKey)) return `Oppdatert i går${time}`;

  const dateOnly = new Date(`${observedKey}T12:00:00Z`);
  const date = new Intl.DateTimeFormat("nb-NO", {
    timeZone: OSLO_TIME_ZONE,
    day: "numeric",
    month: "long",
    year: "numeric",
  }).format(dateOnly);
  return `Oppdatert ${date}${time}`;
}

export type SecondaryWarning = {
  steps: string[];
  translation_queue?: { failed?: number; exhausted?: number; overdue?: number; failed_this_run?: number };
};

type FastJob = {
  stale?: boolean;
  has_error?: boolean;
  status?: string;
  finished_at?: string | null;
  started_at?: string | null;
  secondary_warning?: SecondaryWarning | null;
};

const AREAS: Record<string, string> = {
  dashboard_hot_snapshot: "Mellomlagring av førstesiden",
  investor_snapshots: "Mellomlagring av investordata",
  brazil_snapshot: "Mellomlagring av Brasil-siden",
  bemobi_translation: "Norske Bemobi-dokumenter",
};

export function fastRefreshIssue(job?: FastJob, checkedAt?: string | null) {
  if (!job) return null;
  const common = { state: "DEGRADED" as const, checkedAt, lastRun: job.finished_at ?? job.started_at };
  if (job.stale) return {
    ...common, id: "fast-refresh-stale", title: "Løpende oppdatering er eldre enn forventet",
    detail: "30-minutterskjøringen er eldre enn forventet. Kontroller datadatoene før bruk.",
    affects: "Ferskhet for markedsdata, valuta og førstesiden",
  };
  const warning = job.secondary_warning;
  const steps = warning?.steps ?? [];
  if (job.status === "PARTIAL" && steps.length && steps.every(step => Object.hasOwn(AREAS, step))) {
    const translationOnly = steps.length === 1 && steps[0] === "bemobi_translation";
    const q = warning?.translation_queue;
    const counts = [q?.failed !== undefined ? `${q.failed} dokumenter med feil` : "",
      q?.exhausted !== undefined ? `${q.exhausted} uten flere automatiske forsøk` : "",
      q?.overdue !== undefined ? `${q.overdue} forsinket` : "",
      q?.failed_this_run !== undefined ? `${q.failed_this_run} feil i siste kjøring` : ""].filter(Boolean);
    return {
      ...common, id: "fast-refresh-secondary", badgeLabel: "ADVARSEL",
      title: translationOnly ? "Norsk oversettelse av Bemobi-dokumenter har avvik" : "Sekundære oppgaver har avvik",
      detail: (translationOnly ? "Oversettelseskøen krever oppfølging. Originaldokumentene er fortsatt autoritative." : "En eller flere sekundære oppgaver krever oppfølging.")
        + (counts.length ? " " + counts.join(", ") + "." : "")
        + " NAV-beregningen i kjøringen bestod. Eventuelle egne kilde- eller cacheavvik vises separat.",
      affects: steps.map(step => AREAS[step]).join(", "),
    };
  }
  if (job.has_error || job.status === "FAILED" || job.status === "PARTIAL") return {
    ...common, id: "fast-refresh-error", title: "Siste løpende oppdatering registrerte en feil",
    detail: "30-minutterskjøringen registrerte en feil. Omfanget er ikke bekreftet; kontroller kilde- og NAV-status.",
    affects: "Omfang ikke avklart",
  };
  return null;
}

import { useMemo } from "react";
import { usePollingResource } from "./usePollingResource";
import { formatDate, formatDateTime } from "./uiFormat";
import "./data-quality.css";

const REFRESH_MS = 60_000;

type Job = {
  available?: boolean;
  status?: string;
  started_at?: string | null;
  finished_at?: string | null;
  stale?: boolean;
  has_error?: boolean;
  target_date?: string | null;
  records_written?: number;
  source_health?: Record<string, string>;
  preflight?: {
    ready?: boolean;
    blocker_count?: number;
    warning_count?: number;
    warnings?: Array<{ code: string; message: string }>;
  } | null;
};

type DashboardQuality = {
  available?: boolean;
  status?: string;
  data_status?: string;
  as_of_date?: string | null;
  reasons?: string[];
};

type Runtime = {
  ready: boolean;
  status: string;
  checked_at?: string | null;
  full_refresh?: Job;
  fast_refresh?: Job;
  hot_snapshot?: {
    cache_status?: string;
    valid?: boolean;
    age_seconds?: number | null;
    stored_version?: number | null;
    reason?: string | null;
  };
  dashboard_quality?: DashboardQuality;
  norges_bank?: { status?: string; checked_at?: string | null; has_error?: boolean };
  fx?: { current?: boolean; expected_date?: string | null; latest_common_date?: string | null };
};

type Report = {
  ready: boolean;
  status: string;
  source_period?: string | null;
  report_date?: string | null;
  parser_version?: string | null;
  source_url?: string | null;
  message?: string | null;
  validation?: { valid?: boolean; issue_count?: number };
  pipeline?: {
    newsweb_processed?: boolean;
    pdf_downloaded?: boolean;
    r2_archived?: boolean;
    parsed?: boolean;
    anchors_applied?: boolean;
    nav_rebuilt?: boolean;
  };
  automation?: Record<string, boolean>;
};

type SourceStatusItem = {
  key: string;
  label: string;
  source: string;
  status: string;
  checked_at?: string | null;
  last_good_at?: string | null;
  data_date?: string | null;
  quality?: string | null;
  url?: string | null;
  uses_last_good?: boolean;
  detail?: string | null;
};

type SourceStatus = {
  overall_status: string;
  checked_at?: string | null;
  workflow_status?: string | null;
  items: SourceStatusItem[];
  policy?: string;
};

type QualityState = "OK" | "DEGRADED" | "ERROR" | "WAITING" | "UNKNOWN";
type PipelineState = "OK" | "KJØRER" | "FEIL" | "VENTER" | "IKKE AKTUELL";

type Issue = {
  id: string;
  title: string;
  state: QualityState;
  detail: string;
  lastGood?: string | null;
  checkedAt?: string | null;
  affects?: string | null;
};

const AFFECTED_AREAS: Record<string, string> = {
  norges_bank: "NAV, Oversikt og Brasil",
  b3: "NAV og Bemobi",
  euronext: "NAV, Historikk og Tilbakekjøp",
  yahoo_finance: "NAV og Oversikt",
  newsweb: "Nyheter, rapporter og Tilbakekjøp",
  otello_ir: "NAV og rapportdata",
  life360_ir: "NAV som reservekilde",
  ir: "Bemobi-eierandel og NAV",
  result_release: "Bemobi og NAV",
  consensus: "Konsensus",
  xp_preview: "Konsensus",
};

const CRITICAL_INPUTS = [
  { key: "b3", label: "Bemobi-kurs", source: "B3" },
  { key: "norges_bank", label: "BRL/NOK", source: "Norges Bank" },
  { key: "euronext", label: "OTEC-kurs", source: "Euronext" },
  { key: "yahoo_finance", label: "Life360-kurs", source: "Yahoo Finance" },
  { key: "ir", label: "Bemobi-eierandel", source: "Bemobi IR" },
  { key: "otello_ir", label: "Otello rapportdata", source: "Otello IR" },
] as const;

function normalizeStatus(input?: string | null): QualityState {
  const value = String(input ?? "").toUpperCase();
  if (["OK", "SUCCESS", "APPLIED"].includes(value)) return "OK";
  if (["PARTIAL", "DEGRADED", "ESTIMATED", "REVIEW_REQUIRED"].includes(value)) return "DEGRADED";
  if (["FAILED", "ERROR", "DOWN"].includes(value)) return "ERROR";
  if (["RUNNING", "WAITING"].includes(value)) return "WAITING";
  return "UNKNOWN";
}

function statusLabel(input?: string | null) {
  const state = normalizeStatus(input);
  const labels: Record<QualityState, string> = {
    OK: "OK",
    DEGRADED: "AVVIK",
    ERROR: "FEIL",
    WAITING: "VENTER",
    UNKNOWN: "UKJENT",
  };
  return labels[state];
}

function statusClass(input?: string | null) {
  return `qualityState qualityState${normalizeStatus(input)}`;
}

function statusRank(state: QualityState) {
  return { OK: 0, WAITING: 1, UNKNOWN: 2, DEGRADED: 3, ERROR: 4 }[state];
}

function worstStatus(values: Array<string | null | undefined>): QualityState {
  return values
    .map(normalizeStatus)
    .reduce<QualityState>((worst, current) => (
      statusRank(current) > statusRank(worst) ? current : worst
    ), "OK");
}

function countLabel(count: number, singular: string, plural: string) {
  return `${count} ${count === 1 ? singular : plural}`;
}

function durationLabel(startedAt?: string | null, finishedAt?: string | null) {
  if (!startedAt || !finishedAt) return "–";
  const seconds = Math.max(
    0,
    Math.round((new Date(finishedAt).getTime() - new Date(startedAt).getTime()) / 1000),
  );
  if (!Number.isFinite(seconds)) return "–";
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return minutes ? `${minutes} min ${remainder} sek` : `${remainder} sek`;
}

function sourceDate(item?: SourceStatusItem | null) {
  if (!item) return "–";
  return item.data_date ? formatDate(item.data_date) : "–";
}

function sourceStatusForKey(
  sourceMap: Map<string, SourceStatusItem>,
  key: string,
) {
  return sourceMap.get(key)?.status ?? "UNKNOWN";
}

function PipelineStep({ label, state }: { label: string; state: PipelineState }) {
  const className = `qualityPipelineState pipeline${state.replaceAll(" ", "")}`;
  return (
    <div className="qualityPipelineStep">
      <span className={className} aria-hidden="true" />
      <span>{label}</span>
      <strong>{state}</strong>
    </div>
  );
}

export default function DataQualityPage() {
  const { data: runtime, refreshFailed: runtimeFailed } = usePollingResource<Runtime>(
    "/api/dashboard/runtime-status",
    REFRESH_MS,
    true,
  );
  const { data: report, refreshFailed: reportFailed } = usePollingResource<Report>(
    "/api/dashboard/report-status",
    2 * REFRESH_MS,
    true,
  );
  const { data: sources, refreshFailed: sourcesFailed } = usePollingResource<SourceStatus>(
    "/api/bemobi/source-status",
    2 * REFRESH_MS,
    true,
  );

  const snapshot = runtime?.hot_snapshot;
  const currentQuality = runtime?.dashboard_quality;
  const pipeline = report?.pipeline ?? {};
  const nightly = runtime?.full_refresh;
  const nightlySources = Object.entries(nightly?.source_health ?? {});
  const healthySourceCount = nightlySources.filter(([, status]) => normalizeStatus(status) === "OK").length;
  const sourceItems = sources?.items ?? [];

  const sourceMap = useMemo(
    () => new Map(sourceItems.map((item) => [item.key, item])),
    [sourceItems],
  );

  const navState = currentQuality?.available
    ? normalizeStatus(currentQuality.status)
    : normalizeStatus(runtime?.status);
  const marketState = worstStatus([
    sourceStatusForKey(sourceMap, "b3"),
    sourceStatusForKey(sourceMap, "euronext"),
    sourceStatusForKey(sourceMap, "yahoo_finance"),
  ]);
  const fxState = runtime?.fx?.current === false
    ? "DEGRADED"
    : normalizeStatus(sourceStatusForKey(sourceMap, "norges_bank"));
  const companyState = worstStatus([
    sourceStatusForKey(sourceMap, "ir"),
    sourceStatusForKey(sourceMap, "result_release"),
    sourceStatusForKey(sourceMap, "otello_ir"),
    sourceStatusForKey(sourceMap, "newsweb"),
  ]);
  const overallState = worstStatus([navState, marketState, fxState, companyState]);

  const issues = useMemo<Issue[]>(() => {
    const next: Issue[] = [];

    sourceItems.forEach((item) => {
      const state = normalizeStatus(item.status);
      if (state !== "ERROR" && state !== "DEGRADED") return;
      next.push({
        id: `source-${item.key}`,
        title: `${item.source} — ${item.label}`,
        state,
        detail: item.uses_last_good
          ? `${item.detail ?? "Kilden har et avvik."} Siste gode data er beholdt.`
          : item.detail ?? "Kilden har et registrert avvik.",
        lastGood: item.last_good_at,
        checkedAt: item.checked_at,
        affects: AFFECTED_AREAS[item.key] ?? null,
      });
    });

    if (currentQuality?.available && normalizeStatus(currentQuality.status) !== "OK") {
      const reasons = currentQuality.reasons ?? [];
      next.push({
        id: "dashboard-quality",
        title: "NAV-data har et aktivt kvalitetsavvik",
        state: normalizeStatus(currentQuality.status),
        detail: reasons.join(" ") || "Dashboardkvaliteten er ikke godkjent som OK.",
        checkedAt: runtime?.checked_at,
        affects: "NAV og Oversikt",
      });
    }

    if (runtime?.fast_refresh?.stale) {
      next.push({
        id: "fast-refresh-stale",
        title: "Løpende oppdatering er eldre enn forventet",
        state: "DEGRADED",
        detail: "30-minutterskjøringen er eldre enn forventet. Siste gode data vises inntil en ny kjøring lykkes.",
        lastGood: runtime.fast_refresh.finished_at,
        checkedAt: runtime.checked_at,
        affects: "Markedsdata, valuta og førstesiden",
      });
    } else if (runtime?.fast_refresh?.has_error) {
      next.push({
        id: "fast-refresh-error",
        title: "Siste løpende oppdatering registrerte en feil",
        state: "DEGRADED",
        detail: "Siste 30-minutterskjøring registrerte en feil. Siste gode data beholdes der nye data ikke ble godkjent.",
        lastGood: runtime.fast_refresh.finished_at,
        checkedAt: runtime.checked_at,
        affects: "Markedsdata, valuta og førstesiden",
      });
    }

    if (runtime?.fx?.current === false) {
      next.push({
        id: "fx-stale",
        title: "Valutadata er eldre enn forventet",
        state: "DEGRADED",
        detail: `Siste felles valutadato er ${formatDate(runtime.fx.latest_common_date)}. Forventet minst ${formatDate(runtime.fx.expected_date)}.`,
        checkedAt: runtime.checked_at,
        affects: "NAV, Oversikt og Brasil",
      });
    }

    if (runtimeFailed) {
      next.push({
        id: "runtime-api",
        title: "Kunne ikke oppdatere driftsstatus",
        state: "DEGRADED",
        detail: "Viser siste gode driftsstatus fordi siste API-oppdatering feilet.",
        checkedAt: runtime?.checked_at,
        affects: "Datakvalitet",
      });
    }
    if (sourcesFailed) {
      next.push({
        id: "source-api",
        title: "Kunne ikke oppdatere kildestatus",
        state: "DEGRADED",
        detail: "Viser siste gode kildestatus fordi siste API-oppdatering feilet.",
        checkedAt: sources?.checked_at,
        affects: "Datakvalitet",
      });
    }

    return next;
  }, [currentQuality, runtime, runtimeFailed, sourceItems, sources?.checked_at, sourcesFailed]);

  const heroTitle = overallState === "OK"
    ? "Alle kritiske data er oppdatert"
    : overallState === "ERROR"
      ? "Kritiske data har en feil"
      : overallState === "DEGRADED"
        ? "Data brukes med ett eller flere avvik"
        : "Datastatus er ikke komplett";
  const heroSubtitle = issues.length === 0
    ? "Ingen aktive avvik i dataene som brukes i investorvisningen."
    : `${countLabel(issues.length, "aktivt avvik", "aktive avvik")} krever oppmerksomhet.`;

  const reportState = normalizeStatus(report?.status);
  const reportNeedsAttention = reportFailed || reportState === "ERROR" || reportState === "DEGRADED" || report?.validation?.valid === false;
  const validationFailed = report?.validation?.valid === false;
  const reportSteps: Array<{ label: string; state: PipelineState }> = [
    { label: "NewsWeb", state: pipeline.newsweb_processed ? "OK" : "VENTER" },
    { label: "PDF hentet", state: pipeline.pdf_downloaded ? "OK" : "VENTER" },
    { label: "R2 arkivert", state: pipeline.r2_archived ? "OK" : "VENTER" },
    {
      label: "Validering",
      state: validationFailed ? "FEIL" : pipeline.parsed ? "OK" : reportState === "WAITING" ? "KJØRER" : "VENTER",
    },
    {
      label: "Rapportankre",
      state: validationFailed ? "IKKE AKTUELL" : pipeline.anchors_applied ? "OK" : "VENTER",
    },
    {
      label: "NAV-data bygget",
      state: validationFailed ? "IKKE AKTUELL" : pipeline.nav_rebuilt ? "OK" : "VENTER",
    },
  ];

  const preflightWarnings = nightly?.preflight?.warnings ?? [];

  return (
    <div className="investorPage dataQualityPage">
      <section className="card qualityTrustHero">
        <div className="qualityTrustLead">
          <span className="label">DATAKVALITET NÅ</span>
          <h2>{heroTitle}</h2>
          <p>{heroSubtitle}</p>
          <small>
            Sist kontrollert {formatDateTime(runtime?.checked_at ?? sources?.checked_at)}
            {(runtimeFailed || sourcesFailed) ? " · viser siste gode status der ny kontroll feilet" : ""}
          </small>
        </div>
        <span className={statusClass(overallState)}>{statusLabel(overallState)}</span>
        <div className="qualityTrustDimensions" aria-label="Status for kritiske dataområder">
          {[
            ["NAV-data", navState],
            ["Markedsdata", marketState],
            ["Valuta", fxState],
            ["Selskapsdata", companyState],
          ].map(([label, state]) => (
            <div key={label}>
              <span>{label}</span>
              <strong className={statusClass(state)}>{statusLabel(state)}</strong>
            </div>
          ))}
        </div>
      </section>

      {issues.length > 0 && (
        <section className="card qualityIssuesCard">
          <div className="cardHeader">
            <div>
              <span className="label">AKTIVE AVVIK</span>
              <h2>Dette bør du vite før du bruker tallene</h2>
            </div>
            <span className="pill">{issues.length}</span>
          </div>
          <div className="qualityIssueList">
            {issues.map((issue) => (
              <article className="qualityIssue" key={issue.id}>
                <span className={statusClass(issue.state)}>{statusLabel(issue.state)}</span>
                <div>
                  <strong>{issue.title}</strong>
                  <p>{issue.detail}</p>
                  <div className="qualityIssueMeta">
                    {issue.lastGood && <span>Siste gode: {formatDateTime(issue.lastGood)}</span>}
                    {issue.checkedAt && <span>Kontrollert: {formatDateTime(issue.checkedAt)}</span>}
                    {issue.affects && <span>Påvirker: {issue.affects}</span>}
                  </div>
                </div>
              </article>
            ))}
          </div>
        </section>
      )}

      <section className="card qualityCriticalCard">
        <div className="cardHeader">
          <div>
            <span className="label">KRITISKE NAV-INPUTS</span>
            <h2>Dataene som faktisk driver verdsettelsen</h2>
          </div>
        </div>
        <div className="qualityCriticalTable">
          <div className="qualityCriticalHead" aria-hidden="true">
            <span>Input</span><span>Kilde</span><span>Datadato</span><span>Status</span>
          </div>
          {CRITICAL_INPUTS.map((definition) => {
            const item = sourceMap.get(definition.key);
            const state = item ? normalizeStatus(item.status) : "UNKNOWN";
            const effectiveState = definition.key === "norges_bank" && runtime?.fx?.current === false
              ? "DEGRADED"
              : state;
            return (
              <div className="qualityCriticalRow" key={definition.key}>
                <strong>{definition.label}</strong>
                <span>{item?.source ?? definition.source}</span>
                <span>{sourceDate(item)}</span>
                <span className={statusClass(effectiveState)}>{statusLabel(effectiveState)}</span>
              </div>
            );
          })}
        </div>
        <p className="qualityFootnote">Datadato viser datoen på siste godkjente verdi når kilden oppgir den. Ved avvik beholdes siste validerte data fremfor å nullstille NAV.</p>
      </section>

      <section className="card qualitySourcesCard">
        <div className="cardHeader">
          <div>
            <span className="label">DATAKILDER</span>
            <h2>Kompakt kildeoversikt</h2>
          </div>
          <span className={statusClass(sources?.overall_status)}>{statusLabel(sources?.overall_status)}</span>
        </div>
        {!sources && !sourcesFailed && <p className="dataNotice">Kontrollerer automatiske kilder …</p>}
        {!sources && sourcesFailed && <p className="qualityAlert">Kunne ikke hente kildestatus.</p>}
        {sources && (
          <div className="qualitySourceTable">
            <div className="qualitySourceHead" aria-hidden="true">
              <span>Kilde</span><span>Data</span><span>Status</span><span>Datadato</span><span>Sist kontrollert</span>
            </div>
            {sourceItems.map((item) => (
              <details className="qualitySourceRow" key={item.key}>
                <summary>
                  <span className="qualitySourceName">{item.source}</span>
                  <span>{item.label}</span>
                  <span className={statusClass(item.status)}>{statusLabel(item.status)}</span>
                  <span>{sourceDate(item)}</span>
                  <span>{formatDateTime(item.checked_at)}</span>
                </summary>
                <div className="qualitySourceDetail">
                  <span><b>Brukes av</b>{AFFECTED_AREAS[item.key] ?? "Supplerende investorinformasjon"}</span>
                  <span><b>Siste gode hent</b>{formatDateTime(item.last_good_at)}</span>
                  <span><b>Detalj</b>{item.detail ?? "Ingen ekstra merknad."}</span>
                  {item.uses_last_good && <span><b>Fallback</b>Siste gode data er beholdt.</span>}
                  {item.url && <a href={item.url} target="_blank" rel="noreferrer">Åpne kilde ↗</a>}
                </div>
              </details>
            ))}
          </div>
        )}
      </section>

      <section className={`card qualityReportCard ${reportNeedsAttention ? "qualityReportAttention" : ""}`}>
        <div className="cardHeader">
          <div>
            <span className="label">RAPPORTDATA</span>
            <h2>Automatisk rapportinnlesing</h2>
          </div>
          <span className={statusClass(reportFailed ? "DEGRADED" : report?.status)}>
            {reportFailed ? "SISTE GODE" : statusLabel(report?.status)}
          </span>
        </div>
        {!report?.ready ? (
          <p className="dataNotice">{report?.message ?? "Venter på neste Otello-finansrapport."}</p>
        ) : (
          <>
            <div className="qualityReportSummary">
              <span><b>Periode</b>{report.source_period ?? "–"}</span>
              <span><b>Rapportdato</b>{formatDate(report.report_date)}</span>
              <span><b>Parser</b>{report.parser_version ?? "–"}</span>
              {report.source_url && <a href={report.source_url} target="_blank" rel="noreferrer">Kilde-PDF ↗</a>}
            </div>
            <details className="qualityReportDetails" open={reportNeedsAttention}>
              <summary>{reportNeedsAttention ? "Rapportinnlesingen krever oppmerksomhet" : "Vis rapportpipeline"}</summary>
              <div className="qualityPipeline">
                {reportSteps.map((step) => <PipelineStep key={step.label} {...step} />)}
              </div>
              {validationFailed && (
                <p className="qualityAlert">Rapporten er stoppet av fail-closed-kontrollen. {report.validation?.issue_count ?? 0} valideringsavvik er registrert.</p>
              )}
            </details>
          </>
        )}
      </section>

      <details className="card qualityDiagnostics">
        <summary>
          <span>
            <span className="label">TEKNISK DIAGNOSTIKK</span>
            <strong>Oppdateringsjobber, cache og preflight</strong>
          </span>
          <span className="qualityDiagnosticsSummary">
            Full refresh {statusLabel(nightly?.status)} · Fast refresh {statusLabel(runtime?.fast_refresh?.status)} · Cache {snapshot?.cache_status ?? "UKJENT"}
          </span>
        </summary>
        <div className="qualityDiagnosticsBody">
          <div className="qualityDiagnosticGrid">
            <div>
              <span>Nattoppdatering</span>
              <strong>{statusLabel(nightly?.status)}</strong>
              <small>{formatDate(nightly?.target_date)} · {nightlySources.length ? `${healthySourceCount}/${nightlySources.length} kilder OK` : "kilder ukjent"}</small>
            </div>
            <div>
              <span>Kjøretid natt</span>
              <strong>{durationLabel(nightly?.started_at, nightly?.finished_at)}</strong>
              <small>{nightly?.records_written ?? "–"} oppdaterte datapunkter</small>
            </div>
            <div>
              <span>30-minutterskjøring</span>
              <strong>{statusLabel(runtime?.fast_refresh?.status)}</strong>
              <small>{formatDateTime(runtime?.fast_refresh?.finished_at ?? runtime?.fast_refresh?.started_at)}</small>
            </div>
            <div>
              <span>Førsteside-cache</span>
              <strong>{snapshot?.cache_status ?? "UKJENT"}</strong>
              <small>{snapshot?.age_seconds == null ? snapshot?.reason ?? "–" : `${Math.round(snapshot.age_seconds / 60)} min gammel`}</small>
            </div>
            <div>
              <span>Valuta</span>
              <strong>{runtime?.fx?.current === false ? "AVVIK" : "OK"}</strong>
              <small>Siste felles dato {formatDate(runtime?.fx?.latest_common_date)}</small>
            </div>
            <div>
              <span>Dashboardkvalitet</span>
              <strong>{statusLabel(currentQuality?.status)}</strong>
              <small>{currentQuality?.as_of_date ? `Datadato ${formatDate(currentQuality.as_of_date)}` : "–"}</small>
            </div>
          </div>

          {nightly?.preflight && (
            <div className="qualityPreflight">
              <strong>Preflight</strong>
              <p>
                {countLabel(nightly.preflight.blocker_count ?? 0, "blokkering", "blokkeringer")} · {countLabel(nightly.preflight.warning_count ?? 0, "advarsel", "advarsler")}.
                {nightly.preflight.ready
                  ? " Advarsler stopper ikke oppdateringen når antall blokkeringer er 0."
                  : " Oppdateringen er ikke godkjent; siste gode data beholdes."}
              </p>
              {nightly?.status === "PARTIAL" && nightly.preflight.ready && (
                <p>«Delvis» betyr at kjøringen ble fullført, men at minst én datakilde hadde et avvik.</p>
              )}
              {preflightWarnings.length > 0 && (
                <ul>{preflightWarnings.map((warning) => <li key={`${warning.code}-${warning.message}`}>{warning.message}</li>)}</ul>
              )}
            </div>
          )}
        </div>
      </details>
    </div>
  );
}

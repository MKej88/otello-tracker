import BemobiSourceStatusPanel from "./BemobiSourceStatusPanel";
import { usePollingResource } from "./usePollingResource";
import { formatDate, formatDateTime } from "./uiFormat";

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
  } | null;
};
type Runtime = {
  ready: boolean;
  status: string;
  checked_at?: string | null;
  full_refresh?: Job;
  fast_refresh?: Job;
  hot_snapshot?: { cache_status?: string; valid?: boolean; age_seconds?: number | null; stored_version?: number | null; reason?: string | null };
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
  pipeline?: { newsweb_processed?: boolean; pdf_downloaded?: boolean; r2_archived?: boolean; parsed?: boolean; anchors_applied?: boolean; nav_rebuilt?: boolean };
  automation?: Record<string, boolean>;
};

function statusLabel(input?: string | null) {
  const value = (input ?? "").toUpperCase();
  const labels: Record<string, string> = { SUCCESS: "OK", OK: "OK", PARTIAL: "DELVIS", FAILED: "FEIL", ERROR: "FEIL", RUNNING: "KJØRER", DEGRADED: "AVVIK", MISSING: "MANGLER", APPLIED: "INNLEST", REVIEW_REQUIRED: "KREVER KONTROLL", WAITING: "VENTER" };
  return labels[value] ?? input ?? "UKJENT";
}

function Step({ label, done }: { label: string; done?: boolean }) {
  return <div className="qualityStep"><span className={done ? "qualityDot ok" : "qualityDot"} /><span>{label}</span><strong>{done ? "OK" : "VENTER"}</strong></div>;
}

const SOURCE_LABELS: Record<string, string> = {
  NORGES_BANK: "Norges Bank",
  YAHOO_FINANCE: "Life360 / Yahoo Finance",
  B3: "B3",
  CVM: "CVM",
  BEMOBI_IR: "Bemobi IR",
  NEWSWEB: "NewsWeb",
  EURONEXT: "Euronext / OTEC",
};

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

export default function DataQualityPage() {
  const { data: runtime, refreshFailed: runtimeFailed } = usePollingResource<Runtime>("/api/dashboard/runtime-status", REFRESH_MS);
  const { data: report, refreshFailed: reportFailed } = usePollingResource<Report>("/api/dashboard/report-status", 2 * REFRESH_MS);
  const snapshot = runtime?.hot_snapshot;
  const pipeline = report?.pipeline ?? {};
  const nightly = runtime?.full_refresh;
  const nightlySources = Object.entries(nightly?.source_health ?? {});
  const healthySourceCount = nightlySources.filter(([, status]) => status === "OK").length;

  return (
    <div className="investorPage dataQualityPage">
      <section className="card qualityIntro">
        <div><span className="label">DATAKVALITET</span><h2>Drift, ferskhet og kildekontroll</h2><p>Er dataene oppdatert? Her får du en enkel oversikt over hver datakilde, om den virker, og når vi sist hentet data. Tekniske detaljer ligger lenger ned på siden.</p></div>
        <span className={`qualityOverall ${runtime?.status === "OK" || runtime?.status === "SUCCESS" ? "ok" : ""}`}>{statusLabel(runtime?.status)}</span>
      </section>

      <section className="card nightlySummary">
        <div className="cardHeader">
          <div>
            <span className="label">SISTE NATTKJØRING</span>
            <h2>Nattkjøring {formatDate(nightly?.target_date)}</h2>
          </div>
          <span className={`pill nightlyStatus ${nightly?.status === "SUCCESS" ? "ok" : ""}`}>
            {runtimeFailed ? "SISTE GODE" : statusLabel(nightly?.status)}
          </span>
        </div>
        <div className="nightlyMetrics">
          <div><span>Datadato</span><strong>{formatDate(nightly?.target_date)}</strong></div>
          <div><span>Kjøretid</span><strong>{durationLabel(nightly?.started_at, nightly?.finished_at)}</strong></div>
          <div><span>Oppdaterte datapunkter</span><strong>{nightly?.records_written ?? "–"}</strong></div>
          <div><span>Datakilder</span><strong>{nightlySources.length ? `${healthySourceCount}/${nightlySources.length} OK` : "–"}</strong></div>
        </div>
        {nightlySources.length > 0 && (
          <div className="nightlySources">
            {nightlySources.map(([code, sourceStatus]) => (
              <div key={code}>
                <span className={`qualityDot ${sourceStatus === "OK" ? "ok" : ""}`} />
                <span>{SOURCE_LABELS[code] ?? code}</span>
                <strong>{statusLabel(sourceStatus)}</strong>
              </div>
            ))}
          </div>
        )}
        {nightly?.preflight && (
          <div className="nightlyControl">
            <strong>Datakontroll</strong>
            <span>Preflight: {nightly.preflight.ready ? "OK" : "FEIL"}</span>
            <span>Blokkeringer: {nightly.preflight.blocker_count ?? 0}</span>
            <span>Advarsler: {nightly.preflight.warning_count ?? 0}</span>
          </div>
        )}
      </section>

      <section className="card qualityMethod">
        <div className="cardHeader"><div><span className="label">SLIK FUNGERER DET</span><h2>Fra kilde til tall på siden</h2></div></div>
        <div className="qualityMethodSteps">
          <div><span>1</span><strong>Henter</strong><p>Automatiske jobber leser offisielle rapporter, markedsdata og valuta.</p></div>
          <div><span>2</span><strong>Kontrollerer</strong><p>Dataene valideres før de lagres. Ved feil beholdes siste gode verdi.</p></div>
          <div><span>3</span><strong>Oppdaterer</strong><p>Godkjente data brukes til å bygge NAV og visningene på investorsidene.</p></div>
        </div>
        <p className="qualityMethodNote">«Sist hentet» viser når en verdi sist ble lagret fra kilden. «Sist kontrollert» viser siste forsøk – også når kilden ikke ga nye data.</p>
      </section>

      <BemobiSourceStatusPanel />

      <section className="card">
        <div className="cardHeader"><div><span className="label">DRIFT</span><h2>Automatiske jobber og ferskhet</h2></div><span className="pill">{runtimeFailed ? "SISTE GODE" : statusLabel(runtime?.status)}</span></div>
        <div className="qualityMetricGrid">
          <div><span>Full oppdatering</span><strong>{statusLabel(runtime?.full_refresh?.status)}</strong><small>{formatDateTime(runtime?.full_refresh?.finished_at ?? runtime?.full_refresh?.started_at)}</small></div>
          <div><span>30-min oppdatering</span><strong>{statusLabel(runtime?.fast_refresh?.status)}</strong><small>{formatDateTime(runtime?.fast_refresh?.finished_at ?? runtime?.fast_refresh?.started_at)}</small></div>
          <div><span>Førsteside-cache</span><strong>{snapshot?.cache_status ?? "UKJENT"}</strong><small>{snapshot?.age_seconds == null ? snapshot?.reason ?? "–" : `v${snapshot.stored_version ?? "?"} · ${Math.round(snapshot.age_seconds / 60)} min gammel`}</small></div>
          <div><span>Norges Bank</span><strong>{statusLabel(runtime?.norges_bank?.status)}</strong><small>{formatDateTime(runtime?.norges_bank?.checked_at)}</small></div>
          <div><span>Valuta BRL/USD → NOK</span><strong>{formatDate(runtime?.fx?.latest_common_date)}</strong><small>Forventet minst {formatDate(runtime?.fx?.expected_date)}</small></div>
        </div>
        {(runtime?.full_refresh?.stale || runtime?.fast_refresh?.stale || runtime?.full_refresh?.has_error || runtime?.fast_refresh?.has_error || runtime?.fx?.current === false) && <p className="qualityAlert">Minst ett driftsignal krever oppfølging. Den detaljerte nattdiagnosen lagres også i GitHub.</p>}
      </section>

      <section className="card">
        <div className="cardHeader"><div><span className="label">RAPPORTDATA</span><h2>Automatisk rapportinnlesing</h2></div><span className="pill">{reportFailed ? "SISTE GODE" : statusLabel(report?.status)}</span></div>
        {!report?.ready ? (
          <p className="dataNotice">{report?.message ?? "Venter på neste Otello-finansrapport."}</p>
        ) : (
          <>
            <div className="qualityReportMeta"><div><span>Periode</span><strong>{report.source_period ?? "–"}</strong></div><div><span>Rapportdato</span><strong>{formatDate(report.report_date)}</strong></div><div><span>Parser</span><strong>{report.parser_version ?? "–"}</strong></div>{report.source_url && <a href={report.source_url} target="_blank" rel="noreferrer">Åpne kilde-PDF</a>}</div>
            <div className="qualitySteps">
              <Step label="NewsWeb" done={pipeline.newsweb_processed} />
              <Step label="PDF hentet" done={pipeline.pdf_downloaded} />
              <Step label="R2 arkivert" done={pipeline.r2_archived} />
              <Step label="Validering" done={pipeline.parsed && report.validation?.valid !== false} />
              <Step label="Rapportankre" done={pipeline.anchors_applied} />
              <Step label="NAV-data bygget" done={pipeline.nav_rebuilt} />
            </div>
            {report.validation?.valid === false && <p className="qualityAlert">Rapporten er stoppet av fail-closed-kontrollen. {report.validation.issue_count ?? 0} valideringsavvik er registrert.</p>}
          </>
        )}
      </section>
    </div>
  );
}

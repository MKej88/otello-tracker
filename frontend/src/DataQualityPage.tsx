import BemobiSourceStatusPanel from "./BemobiSourceStatusPanel";
import { usePollingResource } from "./usePollingResource";

const REFRESH_MS = 60_000;

type Job = { available?: boolean; status?: string; started_at?: string | null; finished_at?: string | null; stale?: boolean; has_error?: boolean };
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

function timeLabel(input?: string | null) {
  if (!input) return "–";
  const parsed = new Date(input);
  if (Number.isNaN(parsed.getTime())) return input;
  return parsed.toLocaleString("nb-NO", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function dateLabel(input?: string | null) {
  if (!input) return "–";
  const [year, month, day] = input.slice(0, 10).split("-");
  return year && month && day ? `${day}.${month}.${year}` : input;
}

function Step({ label, done }: { label: string; done?: boolean }) {
  return <div className="qualityStep"><span className={done ? "qualityDot ok" : "qualityDot"} /><span>{label}</span><strong>{done ? "OK" : "VENTER"}</strong></div>;
}

export default function DataQualityPage() {
  const { data: runtime, refreshFailed: runtimeFailed } = usePollingResource<Runtime>("/api/dashboard/runtime-status", REFRESH_MS);
  const { data: report, refreshFailed: reportFailed } = usePollingResource<Report>("/api/dashboard/report-status", 2 * REFRESH_MS);
  const snapshot = runtime?.hot_snapshot;
  const pipeline = report?.pipeline ?? {};

  return (
    <div className="investorPage dataQualityPage">
      <section className="card qualityIntro">
        <div><span className="label">DATAKVALITET</span><h2>Drift, ferskhet og kildekontroll</h2><p>Teknisk informasjon er samlet her og holdes ute av investorsidene. Her ser du om automatiske jobber, cache, valuta, rapportinnlesing og Bemobi-kilder er i orden.</p></div>
        <span className={`qualityOverall ${runtime?.status === "OK" || runtime?.status === "SUCCESS" ? "ok" : ""}`}>{statusLabel(runtime?.status)}</span>
      </section>

      <section className="card">
        <div className="cardHeader"><div><span className="label">DRIFT</span><h2>Automatiske jobber og ferskhet</h2></div><span className="pill">{runtimeFailed ? "SISTE GODE" : statusLabel(runtime?.status)}</span></div>
        <div className="qualityMetricGrid">
          <div><span>Full oppdatering</span><strong>{statusLabel(runtime?.full_refresh?.status)}</strong><small>{timeLabel(runtime?.full_refresh?.finished_at ?? runtime?.full_refresh?.started_at)}</small></div>
          <div><span>30-min oppdatering</span><strong>{statusLabel(runtime?.fast_refresh?.status)}</strong><small>{timeLabel(runtime?.fast_refresh?.finished_at ?? runtime?.fast_refresh?.started_at)}</small></div>
          <div><span>Førsteside-cache</span><strong>{snapshot?.cache_status ?? "UKJENT"}</strong><small>{snapshot?.age_seconds == null ? snapshot?.reason ?? "–" : `v${snapshot.stored_version ?? "?"} · ${Math.round(snapshot.age_seconds / 60)} min gammel`}</small></div>
          <div><span>Norges Bank</span><strong>{statusLabel(runtime?.norges_bank?.status)}</strong><small>{timeLabel(runtime?.norges_bank?.checked_at)}</small></div>
          <div><span>Valuta BRL/USD → NOK</span><strong>{dateLabel(runtime?.fx?.latest_common_date)}</strong><small>Forventet minst {dateLabel(runtime?.fx?.expected_date)}</small></div>
        </div>
        {(runtime?.full_refresh?.stale || runtime?.fast_refresh?.stale || runtime?.full_refresh?.has_error || runtime?.fast_refresh?.has_error || runtime?.fx?.current === false) && <p className="qualityAlert">Minst ett driftsignal krever oppfølging. Den detaljerte nattdiagnosen lagres også i GitHub.</p>}
      </section>

      <section className="card">
        <div className="cardHeader"><div><span className="label">RAPPORTDATA</span><h2>Automatisk rapportinnlesing</h2></div><span className="pill">{reportFailed ? "SISTE GODE" : statusLabel(report?.status)}</span></div>
        {!report?.ready ? (
          <p className="dataNotice">{report?.message ?? "Venter på neste Otello-finansrapport."}</p>
        ) : (
          <>
            <div className="qualityReportMeta"><div><span>Periode</span><strong>{report.source_period ?? "–"}</strong></div><div><span>Rapportdato</span><strong>{dateLabel(report.report_date)}</strong></div><div><span>Parser</span><strong>{report.parser_version ?? "–"}</strong></div>{report.source_url && <a href={report.source_url} target="_blank" rel="noreferrer">Åpne kilde-PDF</a>}</div>
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

      <BemobiSourceStatusPanel />
    </div>
  );
}

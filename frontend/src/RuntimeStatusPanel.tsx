import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { usePollingResource } from "./usePollingResource";
import { formatDate, formatDateTime } from "./uiFormat";
import "./runtime-status.css";

type JobStatus = {
  available: boolean;
  status: string;
  started_at?: string | null;
  finished_at?: string | null;
  target_date?: string | null;
  error_message?: string | null;
  has_error?: boolean;
  stale?: boolean;
  age_minutes?: number | null;
  reason?: string | null;
};

type HotSnapshotStatus = {
  state_key?: string;
  expected_version?: number;
  available?: boolean;
  valid?: boolean;
  cache_status?: "HIT" | "MISS";
  stored_version?: number | null;
  generated_at?: string | null;
  age_seconds?: number | null;
  bytes?: number;
  components?: string[];
  reason?: string | null;
};

type RuntimeStatus = {
  ready: boolean;
  status: string;
  checked_at?: string | null;
  full_refresh: JobStatus;
  fast_refresh: JobStatus;
  hot_snapshot?: HotSnapshotStatus;
  norges_bank: {
    status: string;
    checked_at?: string | null;
    error_message?: string | null;
    has_error?: boolean;
  };
  fx: {
    expected_date?: string | null;
    latest_common_date?: string | null;
    current?: boolean;
  };
};

const REFRESH_MS = 60_000;

function statusLabel(status?: string | null) {
  switch ((status ?? "").toUpperCase()) {
    case "SUCCESS": return "OK";
    case "PARTIAL": return "DELVIS";
    case "FAILED": return "FEIL";
    case "RUNNING": return "KJØRER";
    case "DEGRADED": return "AVVIK";
    case "DOWN": return "FEIL";
    case "MISSING": return "MANGLER";
    default: return status || "UKJENT";
  }
}

function tone(status?: string | null) {
  const normalized = (status ?? "").toUpperCase();
  if (["OK", "SUCCESS"].includes(normalized)) return "ok";
  if (["DOWN", "FAILED", "MISSING"].includes(normalized)) return "bad";
  return "warn";
}

function snapshotDetail(snapshot?: HotSnapshotStatus) {
  if (!snapshot) return "Diagnostikk ikke tilgjengelig";
  if (snapshot.cache_status !== "HIT") return snapshot.reason ?? "Cache mangler";
  const minutes = snapshot.age_seconds == null ? null : Math.max(0, Math.round(snapshot.age_seconds / 60));
  const version = snapshot.stored_version ?? snapshot.expected_version;
  return `v${version ?? "?"}${minutes == null ? "" : ` · ${minutes} min gammel`}`;
}

function RuntimePanel({ data, refreshFailed }: { data: RuntimeStatus | null; refreshFailed: boolean }) {
  if (!data) {
    return (
      <section className="card runtimeStatusCard">
        <div className="runtimeHeader"><div><span className="label">Drift</span><h2>Produksjonsstatus</h2></div><span className="runtimePill warn">LASTER</span></div>
        {refreshFailed && <p className="runtimeError">Kunne ikke hente produksjonsstatus.</p>}
      </section>
    );
  }

  const staleJob = data.full_refresh.stale || data.fast_refresh.stale;
  const hiddenError = data.full_refresh.has_error || data.fast_refresh.has_error || data.norges_bank.has_error;
  const snapshot = data.hot_snapshot;
  const snapshotHit = snapshot?.cache_status === "HIT" && snapshot.valid === true;

  return (
    <section className="card runtimeStatusCard">
      <div className="runtimeHeader">
        <div>
          <span className="label">Drift</span>
          <h2>Produksjonsstatus</h2>
          <p>Automatiske jobber, førsteside-cache og valutaferskhet</p>
        </div>
        <span className={`runtimePill ${tone(data.status)}`}>{statusLabel(data.status)}</span>
      </div>

      <div className="runtimeGrid">
        <div className={`runtimeMetric ${data.full_refresh.stale ? "runtimeMetricWarn" : ""}`}>
          <span>Full oppdatering</span>
          <strong>{statusLabel(data.full_refresh.status)}</strong>
          <small>{formatDateTime(data.full_refresh.finished_at ?? data.full_refresh.started_at)}</small>
        </div>
        <div className={`runtimeMetric ${data.fast_refresh.stale ? "runtimeMetricWarn" : ""}`}>
          <span>30-min oppdatering</span>
          <strong>{statusLabel(data.fast_refresh.status)}</strong>
          <small>{formatDateTime(data.fast_refresh.finished_at ?? data.fast_refresh.started_at)}</small>
        </div>
        <div className={`runtimeMetric ${snapshot && !snapshotHit ? "runtimeMetricWarn" : ""}`}>
          <span>Førsteside-cache</span>
          <strong>{snapshot?.cache_status ?? "UKJENT"}</strong>
          <small>{snapshotDetail(snapshot)}</small>
        </div>
        <div className="runtimeMetric">
          <span>Norges Bank</span>
          <strong>{statusLabel(data.norges_bank.status)}</strong>
          <small>{formatDateTime(data.norges_bank.checked_at)}</small>
        </div>
        <div className={`runtimeMetric ${data.fx.current ? "" : "runtimeMetricWarn"}`}>
          <span>Valuta BRL/USD → NOK</span>
          <strong>{formatDate(data.fx.latest_common_date)}</strong>
          <small>Forventet minst {formatDate(data.fx.expected_date)}</small>
        </div>
      </div>

      {refreshFailed && (
        <div className="runtimeAlert">
          Ny status kunne ikke hentes. Siste gyldige produksjonsstatus beholdes, sist kontrollert {formatDateTime(data.checked_at)}.
        </div>
      )}
      {snapshot && !snapshotHit && (
        <div className="runtimeAlert">
          Førsteside-cachen er ikke klar ({snapshot.reason ?? "ukjent årsak"}). Første innlasting kan derfor bli tregere fordi NAV og markedsdata må beregnes direkte.
        </div>
      )}
      {!data.fx.current && (
        <div className="runtimeAlert">
          Valutaen er eldre enn forventet. 30-minuttersjobben vil forsøke en begrenset Norges Bank-reparasjon automatisk.
        </div>
      )}
      {staleJob && (
        <div className="runtimeAlert">
          En automatisk jobb er eldre enn forventet. Detaljert driftsdiagnose ligger i den private GitHub-kontrollen.
        </div>
      )}
      {hiddenError && (
        <p className="runtimeError">Et produksjonsavvik er registrert. Detaljer vises kun i privat driftsdiagnostikk.</p>
      )}
    </section>
  );
}

export default function RuntimeStatusMount() {
  const [target, setTarget] = useState<Element | null>(null);
  const { data, refreshFailed } = usePollingResource<RuntimeStatus>(
    "/api/dashboard/runtime-status",
    REFRESH_MS,
  );

  useEffect(() => {
    setTarget(document.querySelector(".main"));
  }, []);

  if (!target) return null;
  return createPortal(<RuntimePanel data={data} refreshFailed={refreshFailed} />, target);
}

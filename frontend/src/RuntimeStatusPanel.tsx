import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import "./runtime-status.css";

type JobStatus = {
  available: boolean;
  status: string;
  started_at?: string | null;
  finished_at?: string | null;
  target_date?: string | null;
  records_written?: number;
  error_message?: string | null;
};

type SourceStatus = {
  source: string;
  status: string;
  checked_at?: string | null;
  error_message?: string | null;
};

type FxRow = {
  pair: string;
  observed_at?: string | null;
  rate?: string | number | null;
  fetched_at?: string | null;
  source?: string | null;
};

type JobError = {
  job_name?: string | null;
  status?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  error_message?: string | null;
};

type RuntimeStatus = {
  ready: boolean;
  status: string;
  checked_at?: string | null;
  full_refresh: JobStatus;
  fast_refresh: JobStatus;
  sources?: SourceStatus[];
  norges_bank: {
    status: string;
    checked_at?: string | null;
    last_write_at?: string | null;
    error_message?: string | null;
  };
  fx: {
    expected_date?: string | null;
    latest_common_date?: string | null;
    current?: boolean;
    latest_rows?: FxRow[];
  };
  recent_job_errors?: JobError[];
  d1?: {
    status?: string | null;
    latest_activity_at?: string | null;
    age_seconds?: number | null;
    signals?: {
      latest_job_at?: string | null;
      latest_source_health_at?: string | null;
      latest_fx_write_at?: string | null;
    };
  };
  security?: {
    read_only?: boolean;
    raw_metadata_exposed?: boolean;
    errors_redacted?: boolean;
  };
};

const REFRESH_MS = 60_000;
const SOURCE_LABELS: Record<string, string> = {
  NORGES_BANK: "Norges Bank",
  B3: "B3",
  CVM: "CVM",
  BEMOBI_IR: "Bemobi IR",
  NEWSWEB: "NewsWeb",
  EURONEXT: "Euronext",
};

function dateLabel(input?: string | null) {
  if (!input) return "–";
  const value = input.slice(0, 10);
  const [year, month, day] = value.split("-");
  return year && month && day ? `${day}.${month}.${year}` : input;
}

function timeLabel(input?: string | null) {
  if (!input) return "–";
  const parsed = new Date(input);
  if (Number.isNaN(parsed.getTime())) return input;
  return parsed.toLocaleString("nb-NO", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function ageLabel(seconds?: number | null) {
  if (seconds == null || !Number.isFinite(seconds)) return "–";
  if (seconds < 60) return `${Math.max(0, Math.round(seconds))} sek siden`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min siden`;
  return `${(seconds / 3600).toLocaleString("nb-NO", { maximumFractionDigits: 1 })} t siden`;
}

function rateLabel(input?: string | number | null) {
  const value = Number(input);
  if (!Number.isFinite(value)) return "–";
  return value.toLocaleString("nb-NO", { minimumFractionDigits: 4, maximumFractionDigits: 6 });
}

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

function ErrorText({ value }: { value?: string | null }) {
  if (!value) return null;
  return <div className="runtimeInlineError">{value}</div>;
}

function RuntimePanel({ data }: { data: RuntimeStatus | null }) {
  if (!data) {
    return (
      <section className="card runtimeStatusCard">
        <div className="runtimeHeader"><div><span className="label">Drift</span><h2>Produksjonsstatus</h2></div><span className="runtimePill warn">LASTER</span></div>
      </section>
    );
  }

  const sources = data.sources ?? [];
  const fxRows = data.fx.latest_rows ?? [];
  const jobErrors = data.recent_job_errors ?? [];

  return (
    <section className="card runtimeStatusCard">
      <div className="runtimeHeader">
        <div>
          <span className="label">Drift</span>
          <h2>Produksjonsstatus</h2>
          <p>Read-only kontroll av jobber, datakilder, valuta og D1</p>
        </div>
        <span className={`runtimePill ${tone(data.status)}`}>{statusLabel(data.status)}</span>
      </div>

      <div className="runtimeGrid runtimeGridFive">
        <div className="runtimeMetric">
          <span>Full oppdatering</span>
          <strong>{statusLabel(data.full_refresh.status)}</strong>
          <small>{timeLabel(data.full_refresh.finished_at ?? data.full_refresh.started_at)}</small>
        </div>
        <div className="runtimeMetric">
          <span>30-min oppdatering</span>
          <strong>{statusLabel(data.fast_refresh.status)}</strong>
          <small>{timeLabel(data.fast_refresh.finished_at ?? data.fast_refresh.started_at)}</small>
        </div>
        <div className="runtimeMetric">
          <span>Norges Bank</span>
          <strong>{statusLabel(data.norges_bank.status)}</strong>
          <small>Sist skrev {timeLabel(data.norges_bank.last_write_at)}</small>
        </div>
        <div className={`runtimeMetric ${data.fx.current ? "" : "runtimeMetricWarn"}`}>
          <span>Valuta BRL/USD → NOK</span>
          <strong>{dateLabel(data.fx.latest_common_date)}</strong>
          <small>Forventet minst {dateLabel(data.fx.expected_date)}</small>
        </div>
        <div className={`runtimeMetric ${tone(data.d1?.status) === "ok" ? "" : "runtimeMetricWarn"}`}>
          <span>D1-ferskhet</span>
          <strong>{statusLabel(data.d1?.status)}</strong>
          <small>{ageLabel(data.d1?.age_seconds)}</small>
        </div>
      </div>

      {!data.fx.current && (
        <div className="runtimeAlert">
          Valutaen er eldre enn forventet. 30-minuttersjobben vil forsøke en begrenset Norges Bank-reparasjon automatisk.
        </div>
      )}

      <details className="runtimeDetails">
        <summary>Vis driftsdetaljer</summary>

        <div className="runtimeDetailSection">
          <div className="runtimeDetailTitle">
            <h3>Kilder</h3>
            <small>Siste registrerte source_health per kilde</small>
          </div>
          <div className="runtimeSourceGrid">
            {sources.map((source) => (
              <div className="runtimeSource" key={source.source}>
                <div>
                  <strong>{SOURCE_LABELS[source.source] ?? source.source}</strong>
                  <small>{timeLabel(source.checked_at)}</small>
                </div>
                <span className={`runtimeMiniPill ${tone(source.status)}`}>{statusLabel(source.status)}</span>
                <ErrorText value={source.error_message} />
              </div>
            ))}
          </div>
        </div>

        <div className="runtimeDetailSection">
          <div className="runtimeDetailTitle">
            <h3>Siste FX-rader</h3>
            <small>Norges Bank · direkte D1-lesing</small>
          </div>
          <div className="runtimeTableWrap">
            <table className="runtimeTable">
              <thead><tr><th>Par</th><th>Dato</th><th>Kurs</th><th>Hentet</th></tr></thead>
              <tbody>
                {fxRows.length === 0 && <tr><td colSpan={4}>Ingen FX-rader funnet.</td></tr>}
                {fxRows.map((row, index) => (
                  <tr key={`${row.pair}-${row.observed_at}-${index}`}>
                    <td>{row.pair}</td>
                    <td>{dateLabel(row.observed_at)}</td>
                    <td>{rateLabel(row.rate)}</td>
                    <td>{timeLabel(row.fetched_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="runtimeDetailSection runtimeTwoColumns">
          <div>
            <div className="runtimeDetailTitle">
              <h3>D1-puls</h3>
              <small>Tre uavhengige aktivitetssignaler</small>
            </div>
            <dl className="runtimeSignalList">
              <div><dt>Siste jobb</dt><dd>{timeLabel(data.d1?.signals?.latest_job_at)}</dd></div>
              <div><dt>Kildehelse</dt><dd>{timeLabel(data.d1?.signals?.latest_source_health_at)}</dd></div>
              <div><dt>FX-skriving</dt><dd>{timeLabel(data.d1?.signals?.latest_fx_write_at)}</dd></div>
            </dl>
          </div>
          <div>
            <div className="runtimeDetailTitle">
              <h3>Siste jobbfeil</h3>
              <small>Kun sanitert feiltekst fra job_runs</small>
            </div>
            <div className="runtimeJobErrors">
              {jobErrors.length === 0 && <p>Ingen nylige PARTIAL/FAILED-jobber med feiltekst.</p>}
              {jobErrors.map((error, index) => (
                <div className="runtimeJobError" key={`${error.job_name}-${error.finished_at}-${index}`}>
                  <div><strong>{error.job_name ?? "Ukjent jobb"}</strong><span>{statusLabel(error.status)}</span></div>
                  <small>{timeLabel(error.finished_at ?? error.started_at)}</small>
                  <ErrorText value={error.error_message} />
                </div>
              ))}
            </div>
          </div>
        </div>

        <p className="runtimeSecurityNote">
          Read-only driftsflate. Rå metadata returneres ikke, og kjente credentials/URL-parametre maskeres i feiltekst.
        </p>
      </details>

      {(data.full_refresh.error_message || data.fast_refresh.error_message || data.norges_bank.error_message) && (
        <p className="runtimeError">{data.norges_bank.error_message ?? data.full_refresh.error_message ?? data.fast_refresh.error_message}</p>
      )}
    </section>
  );
}

export default function RuntimeStatusMount() {
  const [target, setTarget] = useState<Element | null>(null);
  const [data, setData] = useState<RuntimeStatus | null>(null);

  useEffect(() => {
    setTarget(document.querySelector(".main"));
  }, []);

  useEffect(() => {
    let active = true;
    const load = () => {
      fetch("/api/dashboard/runtime-status", { cache: "no-store" })
        .then((response) => {
          if (!response.ok) throw new Error("Runtime status API-feil");
          return response.json() as Promise<RuntimeStatus>;
        })
        .then((result) => { if (active) setData(result); })
        .catch(() => { if (active) setData(null); });
    };
    load();
    const timer = window.setInterval(load, REFRESH_MS);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  if (!target) return null;
  return createPortal(<RuntimePanel data={data} />, target);
}

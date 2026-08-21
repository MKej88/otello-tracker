import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import "./runtime-status.css";

type JobStatus = {
  available: boolean;
  status: string;
  started_at?: string | null;
  finished_at?: string | null;
  target_date?: string | null;
  error_message?: string | null;
};

type RuntimeStatus = {
  ready: boolean;
  status: string;
  checked_at?: string | null;
  full_refresh: JobStatus;
  fast_refresh: JobStatus;
  norges_bank: {
    status: string;
    checked_at?: string | null;
    error_message?: string | null;
  };
  fx: {
    expected_date?: string | null;
    latest_common_date?: string | null;
    current?: boolean;
  };
};

const REFRESH_MS = 60_000;

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

function RuntimePanel({ data }: { data: RuntimeStatus | null }) {
  if (!data) {
    return (
      <section className="card runtimeStatusCard">
        <div className="runtimeHeader"><div><span className="label">Drift</span><h2>Produksjonsstatus</h2></div><span className="runtimePill warn">LASTER</span></div>
      </section>
    );
  }

  return (
    <section className="card runtimeStatusCard">
      <div className="runtimeHeader">
        <div>
          <span className="label">Drift</span>
          <h2>Produksjonsstatus</h2>
          <p>Automatiske jobber og valutaferskhet</p>
        </div>
        <span className={`runtimePill ${tone(data.status)}`}>{statusLabel(data.status)}</span>
      </div>

      <div className="runtimeGrid">
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
          <small>{timeLabel(data.norges_bank.checked_at)}</small>
        </div>
        <div className={`runtimeMetric ${data.fx.current ? "" : "runtimeMetricWarn"}`}>
          <span>Valuta BRL/USD → NOK</span>
          <strong>{dateLabel(data.fx.latest_common_date)}</strong>
          <small>Forventet minst {dateLabel(data.fx.expected_date)}</small>
        </div>
      </div>

      {!data.fx.current && (
        <div className="runtimeAlert">
          Valutaen er eldre enn forventet. 30-minuttersjobben vil forsøke en begrenset Norges Bank-reparasjon automatisk.
        </div>
      )}
      {(data.full_refresh.error_message || data.norges_bank.error_message) && (
        <p className="runtimeError">{data.norges_bank.error_message ?? data.full_refresh.error_message}</p>
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
      fetch("/api/dashboard/runtime-status")
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

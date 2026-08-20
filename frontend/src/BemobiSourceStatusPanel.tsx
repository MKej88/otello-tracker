import { useEffect, useState } from "react";
import "./bemobi-source-status.css";


type SourceStatusItem = {
  key: string;
  label: string;
  source: string;
  status: "OK" | "DEGRADED" | "ERROR" | "WAITING" | "UNKNOWN" | string;
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

const AUTO_REFRESH_MS = 2 * 60 * 1000;

function dateTimeLabel(input?: string | null) {
  if (!input) return "–";
  const parsed = new Date(input);
  if (Number.isNaN(parsed.getTime())) return input;
  return parsed.toLocaleString("nb-NO", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  });
}

function dateLabel(input?: string | null) {
  if (!input) return "–";
  const [year, month, day] = input.slice(0, 10).split("-");
  return year && month && day ? `${day}.${month}.${year}` : input;
}

function statusLabel(status: string) {
  const labels: Record<string, string> = {
    OK: "OK",
    PARTIAL: "DELVIS",
    DEGRADED: "SISTE GODE DATA",
    ERROR: "FEIL",
    WAITING: "VENTER",
    UNKNOWN: "IKKE KONTROLLERT"
  };
  return labels[status] ?? status;
}

export default function BemobiSourceStatusPanel() {
  const [data, setData] = useState<SourceStatus | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    const load = () => {
      fetch("/api/bemobi/source-status")
        .then((response) => {
          if (!response.ok) throw new Error("Datakildestatus API-feil");
          return response.json() as Promise<SourceStatus>;
        })
        .then((result) => {
          if (!active) return;
          setData(result);
          setFailed(false);
        })
        .catch(() => {
          if (!active) return;
          setFailed(true);
        });
    };

    load();
    const timer = window.setInterval(load, AUTO_REFRESH_MS);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  if (data == null && !failed) {
    return (
      <section className="card bemobiSources bemobiSourceStatus">
        <div className="cardHeader">
          <div><span className="label">Datakilder</span><h2>Kontrollerer automatiske kilder …</h2></div>
        </div>
      </section>
    );
  }

  if (data == null) {
    return (
      <section className="card bemobiSources bemobiSourceStatus">
        <div className="cardHeader">
          <div><span className="label">Datakilder</span><h2>Kunne ikke hente kildestatus</h2></div>
          <span className="pill muted">API-FEIL</span>
        </div>
      </section>
    );
  }

  return (
    <section className="card bemobiSources bemobiSourceStatus">
      <div className="cardHeader">
        <div>
          <span className="label">Datakilder</span>
          <h2>Automatisk kildekontroll</h2>
        </div>
        <span className="pill">{statusLabel(data.overall_status)}</span>
      </div>

      <div className="sourceList">
        {(data.items ?? []).map((item) => (
          <div key={item.key}>
            <span>
              {item.label}
              <small>
                Kontrollert {dateTimeLabel(item.checked_at)} · datadato {dateLabel(item.data_date)}
              </small>
              {item.detail && <small>{item.detail}</small>}
            </span>
            <strong>
              {item.url ? (
                <a href={item.url} target="_blank" rel="noreferrer">
                  {item.source} · {statusLabel(item.status)}
                </a>
              ) : (
                <>{item.source} · {statusLabel(item.status)}</>
              )}
              {item.uses_last_good && <small>bruker siste gode verdi</small>}
            </strong>
          </div>
        ))}
      </div>

      <p className="bemobiFootnote">
        Offisielle kilder prioriteres. Hvis MarketScreener eller en annen sekundær kilde feiler,
        beholdes siste validerte verdi i stedet for å nullstille eller erstatte den med usikre data.
      </p>
    </section>
  );
}

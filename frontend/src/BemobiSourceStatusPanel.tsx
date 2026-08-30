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

const USED_ON: Record<string, string> = {
  norges_bank: "NAV og oversikt",
  b3: "NAV og Bemobi",
  euronext: "NAV, historikk og tilbakekjøp",
  yahoo_finance: "NAV og oversikt",
  newsweb: "Nyheter, rapporter og tilbakekjøp",
  otello_ir: "NAV og rapporter",
  life360_ir: "NAV og oversikt",
  ir: "Bemobi",
  result_release: "Bemobi og NAV",
  consensus: "Konsensus og Bemobi",
  xp_preview: "Konsensus",
};

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
    const loadStatus = () => {
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
    loadStatus();
    const timer = window.setInterval(() => {
      loadStatus();
    }, AUTO_REFRESH_MS);
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
          <span className="label">KILDEOVERSIKT</span>
          <h2>Status for hver kilde</h2>
        </div>
        <span className="pill">{statusLabel(data.overall_status)}</span>
      </div>

      <div className="sourceStatusTable">
        <div className="sourceStatusHead" aria-hidden="true">
          <span>Datakilde</span><span>Hva den henter</span><span>Brukes på side</span><span>Status</span><span>Sist hentet</span><span>Sist kontrollert</span>
        </div>
        {(data.items ?? []).map((item) => (
          <div className="sourceStatusRow" key={item.key}>
            <span className="sourceStatusSource">
              {item.url ? (
                <a href={item.url} target="_blank" rel="noreferrer">
                  {item.source} ↗
                </a>
              ) : (
                item.source
              )}
            </span>
            <span className="sourceStatusName"><strong>{item.label}</strong><small>Datadato {dateLabel(item.data_date)}</small></span>
            <span>{USED_ON[item.key] ?? "–"}</span>
            <span><strong className={`sourceStatusBadge sourceStatus-${item.status.toLowerCase()}`}><i aria-hidden="true" />{statusLabel(item.status)}</strong>{item.uses_last_good && <small>Bruker siste gode verdi</small>}</span>
            <span><b className="mobileSourceLabel">Sist hentet</b>{dateTimeLabel(item.last_good_at)}</span>
            <span><b className="mobileSourceLabel">Sist kontrollert</b>{dateTimeLabel(item.checked_at)}</span>
            {item.detail && <small className="sourceStatusDetail">{item.detail}</small>}
          </div>
        ))}
      </div>

      <p className="bemobiFootnote">
        Oversikten viser alle automatiske kilder som brukes i løsningen. Offisielle kilder prioriteres. Hvis MarketScreener eller en annen sekundær kilde feiler,
        beholdes siste validerte verdi i stedet for å nullstille eller erstatte den med usikre data.
      </p>
    </section>
  );
}

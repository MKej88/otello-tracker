import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./styles.css";
import "./prelive.css";

const AUTO_REFRESH_MS = 2 * 60 * 1000;

type TimestampSummary = {
  ready?: boolean;
  market_timestamps?: {
    status?: string;
    otec?: { date?: string | null };
    bmob3?: { date?: string | null };
    brl_nok?: { date?: string | null };
  };
};

function shortDate(value?: string | null) {
  if (!value) return "–";
  const [year, month, day] = value.split("-");
  if (!year || !month || !day) return value;
  return `${day}.${month}`;
}

function LiveDashboard() {
  const [revision, setRevision] = React.useState(0);
  const [timestamps, setTimestamps] = React.useState<TimestampSummary["market_timestamps"]>();

  const loadTimestampStatus = React.useCallback(() => {
    fetch("/api/dashboard/summary")
      .then((response) => response.ok ? response.json() as Promise<TimestampSummary> : null)
      .then((payload) => {
        if (payload?.ready) setTimestamps(payload.market_timestamps);
      })
      .catch(() => undefined);
  }, []);

  React.useEffect(() => {
    loadTimestampStatus();
    const timer = window.setInterval(() => {
      setRevision((value) => value + 1);
      loadTimestampStatus();
    }, AUTO_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [loadTimestampStatus]);

  const status = timestamps?.status ?? "UNKNOWN";
  return (
    <>
      <App key={revision} />
      <div className={`freshnessBadge freshness-${status.toLowerCase()}`} title="Datoene på markedsinputene som inngår i siste NAV">
        <span className="freshnessDot" />
        <strong>{status}</strong>
        <span>OTEC {shortDate(timestamps?.otec?.date)}</span>
        <span>BMOB3 {shortDate(timestamps?.bmob3?.date)}</span>
        <span>FX {shortDate(timestamps?.brl_nok?.date)}</span>
      </div>
    </>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <LiveDashboard />
  </React.StrictMode>
);

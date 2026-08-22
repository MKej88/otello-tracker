from pathlib import Path
import re


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"Mangler forventet blokk: {label}")
    return text.replace(old, new, 1)


app_path = Path("frontend/src/App.tsx")
app = app_path.read_text(encoding="utf-8")

app = replace_once(
    app,
    '''import { useEffect, useMemo, useState } from "react";
import BemobiPage from "./BemobiPage";
import BuybackPage from "./BuybackPage";
import ConsensusPage from "./ConsensusPage";
import EconomicNavPanel from "./EconomicNavPanel";
import HistoryPage from "./HistoryPage";
import NavWaterfallPanel from "./NavWaterfallPanel";''',
    '''import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import EconomicNavPanel from "./EconomicNavPanel";

const loadBemobiPage = () => import("./BemobiPage");
const loadBuybackPage = () => import("./BuybackPage");
const loadConsensusPage = () => import("./ConsensusPage");
const loadHistoryPage = () => import("./HistoryPage");
const loadNavWaterfallPanel = () => import("./NavWaterfallPanel");

const BemobiPage = lazy(loadBemobiPage);
const BuybackPage = lazy(loadBuybackPage);
const ConsensusPage = lazy(loadConsensusPage);
const HistoryPage = lazy(loadHistoryPage);
const NavWaterfallPanel = lazy(loadNavWaterfallPanel);''',
    "eager imports",
)

effect_pattern = re.compile(
    r'  useEffect\(\(\) => \{\n    let active = true;\n\n    const loadDashboard = \(\) => \{.*?\n  \}, \[\]\);',
    re.S,
)
new_effects = '''  useEffect(() => {
    let active = true;
    let inFlight = false;

    const loadSummary = async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        const response = await fetch("/api/dashboard/summary");
        if (!response.ok) throw new Error("Summary API-feil");
        const summaryData = await response.json() as Summary;
        if (!active) return;
        setSummary(summaryData);
        setApiOk(true);
        setRefreshFailed(false);
        setLastSuccessfulFetchAt(new Date().toLocaleTimeString("nb-NO", {
          hour: "2-digit",
          minute: "2-digit"
        }));
      } catch {
        if (!active) return;
        setApiOk(false);
        setRefreshFailed(true);
        setSummary((current) => current.ready
          ? current
          : { ready: false, data_status: "error", message: "Kunne ikke hente investordata." });
      } finally {
        inFlight = false;
      }
    };

    void loadSummary();
    const timer = window.setInterval(() => { void loadSummary(); }, AUTO_REFRESH_MS);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    if (!summary.ready) return undefined;
    let active = true;
    let inFlight = false;

    const loadForecast = async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        const response = await fetch("/api/buybacks/forecast");
        if (!response.ok) throw new Error("Forecast API-feil");
        const forecastData = await response.json() as BuybackForecast;
        if (!active) return;
        setForecast(forecastData);
      } catch {
        if (!active) return;
        setForecast((current) => current.ready
          ? { ...current, status: "FETCH_STALE" }
          : { ready: false, status: "API_ERROR" });
      } finally {
        inFlight = false;
      }
    };

    const initialTimer = window.setTimeout(() => { void loadForecast(); }, 600);
    const timer = window.setInterval(() => { void loadForecast(); }, AUTO_REFRESH_MS);
    return () => {
      active = false;
      window.clearTimeout(initialTimer);
      window.clearInterval(timer);
    };
  }, [summary.ready]);

  useEffect(() => {
    if (activeView !== "NAV") return undefined;
    let active = true;
    let inFlight = false;

    const loadHistory = async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        const response = await fetch("/api/dashboard/history?days=365&max_points=300");
        if (!response.ok) throw new Error("History API-feil");
        const historyData = await response.json() as History;
        if (!active) return;
        setHistory(historyData);
      } catch {
        if (!active) return;
        setHistory((current) => current.ready
          ? current
          : { ready: false, data_status: "error", points: [] });
      } finally {
        inFlight = false;
      }
    };

    void loadHistory();
    const timer = window.setInterval(() => { void loadHistory(); }, AUTO_REFRESH_MS);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [activeView]);'''
app, count = effect_pattern.subn(lambda _: new_effects, app, count=1)
if count != 1:
    raise SystemExit(f"Forventet én dashboard-effekt, fant {count}")

helper = '''
function preloadView(view: View) {
  if (view === "Historikk") void loadHistoryPage();
  else if (view === "Tilbakekjøp") void loadBuybackPage();
  else if (view === "Bemobi") void loadBemobiPage();
  else if (view === "Konsensus") void loadConsensusPage();
  else if (view === "NAV") void loadNavWaterfallPanel();
}

function ViewFallback() {
  return (
    <section className="card" aria-busy="true">
      <span className="label">Visning</span>
      <strong>Laster modul …</strong>
    </section>
  );
}
'''
app = replace_once(app, "\nexport default function App()", "\n" + helper + "\nexport default function App()", "App export")

app = replace_once(
    app,
    '''                onClick={() => item.enabled && setActiveView(item.label as View)}
                title={item.enabled ? undefined : "Denne visningen er ikke aktiv ennå"}''',
    '''                onClick={() => item.enabled && setActiveView(item.label as View)}
                onMouseEnter={() => item.enabled && preloadView(item.label as View)}
                onFocus={() => item.enabled && preloadView(item.label as View)}
                onPointerDown={() => item.enabled && preloadView(item.label as View)}
                title={item.enabled ? undefined : "Denne visningen er ikke aktiv ennå"}''',
    "navigation prefetch",
)

for old, new, label in (
    ('          <HistoryPage />', '          <Suspense fallback={<ViewFallback />}><HistoryPage /></Suspense>', "HistoryPage"),
    ('          <BuybackPage />', '          <Suspense fallback={<ViewFallback />}><BuybackPage /></Suspense>', "BuybackPage"),
    ('          <BemobiPage />', '          <Suspense fallback={<ViewFallback />}><BemobiPage /></Suspense>', "BemobiPage"),
    ('          <ConsensusPage />', '          <Suspense fallback={<ViewFallback />}><ConsensusPage /></Suspense>', "ConsensusPage"),
    ('            <NavWaterfallPanel />', '            <Suspense fallback={<ViewFallback />}><NavWaterfallPanel /></Suspense>', "NavWaterfallPanel"),
):
    app = replace_once(app, old, new, label)

app_path.write_text(app, encoding="utf-8")

economic_path = Path("frontend/src/EconomicNavPanel.tsx")
economic = economic_path.read_text(encoding="utf-8")
loading_pattern = re.compile(
    r'  if \(data == null\) \{\n    if \(!refreshFailed\).*?\n  \}\n\n  if \(!data\.ready\)',
    re.S,
)
new_loading = '''  if (data == null) {
    return (
      <section className="economicNavHost">
        <div className="economicNavPanel economicNavUnavailable" aria-busy={!refreshFailed}>
          <div>
            <span className="economicEyebrow">Investorjustert NAV</span>
            <strong>{refreshFailed ? "Økonomisk NAV kunne ikke hentes" : "Henter økonomisk NAV …"}</strong>
          </div>
          <span>{refreshFailed ? reasonLabel("api_error") : "LASTER"}</span>
        </div>
        {variant === "summary" && <MarketQuotePanel />}
      </section>
    );
  }

  if (!data.ready)'''
economic, count = loading_pattern.subn(lambda _: new_loading, economic, count=1)
if count != 1:
    raise SystemExit(f"Forventet én EconomicNav-loadingblokk, fant {count}")
economic_path.write_text(economic, encoding="utf-8")

Path("frontend/src/DeferredDiagnostics.tsx").write_text('''import { lazy, Suspense, useEffect, useState } from "react";

const ReportStatusMount = lazy(() => import("./ReportStatusPanel"));
const RuntimeStatusMount = lazy(() => import("./RuntimeStatusPanel"));

export default function DeferredDiagnostics() {
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let timer: number | null = null;
    const schedule = () => {
      timer = window.setTimeout(() => setReady(true), 4000);
    };

    if (document.readyState === "complete") schedule();
    else window.addEventListener("load", schedule, { once: true });

    return () => {
      window.removeEventListener("load", schedule);
      if (timer != null) window.clearTimeout(timer);
    };
  }, []);

  if (!ready) return null;
  return (
    <Suspense fallback={null}>
      <ReportStatusMount />
      <RuntimeStatusMount />
    </Suspense>
  );
}
''', encoding="utf-8")

Path("frontend/src/main.tsx").write_text('''import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import DeferredDiagnostics from "./DeferredDiagnostics";
import "./styles.css";
import "./prelive.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
    <DeferredDiagnostics />
  </React.StrictMode>
);
''', encoding="utf-8")

Path("tools/perf_refactor_tmp.py").unlink()
Path(".github/workflows/perf-refactor-temp.yml").unlink()

import { lazy, Suspense, useEffect, useState, type MouseEvent } from "react";
import InvestorNavigation from "./InvestorNavigation";
import LoadingPlaceholder from "./LoadingPlaceholder";
import {
  type View,
  viewFromHash,
  viewSlugs,
  viewSubtitles,
  viewTitles,
} from "./investorViews";
import { installDashboardBootstrapFetch } from "./dashboardBootstrapFetch";
import { discountHistoryUrl, investorPeriods } from "./investorPeriods";
import { preloadJson, preloadNavPeriodBundle } from "./navigationDataPreload";
import {
  PageUpdateProvider,
  pageUpdateIsStale,
  pageUpdateLabel,
  type PageUpdate,
} from "./pageUpdateStatus";

const loadOverviewPage = () => import("./OverviewPage");
const loadNavPage = () => import("./NavPageV2");
const loadNavSensitivityPage = () => import("./NavSensitivityPage");
const loadHistoryPage = () => import("./EstimatedHistoryPage");
const loadBuybackPage = () => import("./BuybackPage");
const loadCashPage = () => import("./CashPage");
const loadBemobiPage = () => import("./BemobiPage");
const loadFxPage = () => import("./FxPage");
const loadBrazilPage = () => import("./BrazilPage");
const loadConsensusPage = () => import("./ConsensusPage");
const loadDataQualityPage = () => import("./DataQualityPage");
const loadNewsEventsPage = () => import("./NewsEventsPage");

const OverviewPage = lazy(loadOverviewPage);
const NavPageV2 = lazy(loadNavPage);
const NavSensitivityPage = lazy(loadNavSensitivityPage);
const EstimatedHistoryPage = lazy(loadHistoryPage);
const BuybackPage = lazy(loadBuybackPage);
const CashPage = lazy(loadCashPage);
const BemobiPage = lazy(loadBemobiPage);
const FxPage = lazy(loadFxPage);
const BrazilPage = lazy(loadBrazilPage);
const ConsensusPage = lazy(loadConsensusPage);
const DataQualityPage = lazy(loadDataQualityPage);
const NewsEventsPage = lazy(loadNewsEventsPage);

function ViewFallback() {
  return <LoadingPlaceholder className="loadingPlaceholderPage" label="Laster valgt visning" />;
}

function preload(view: View) {
  if (view === "Oversikt") {
    void loadOverviewPage();
    installDashboardBootstrapFetch();
    preloadJson("/api/dashboard/discount-history?days=365&max_points=72");
  }
  if (view === "NAV") {
    void loadNavPage();
    preloadJson("/api/dashboard/economic");
    preloadJson("/api/buybacks/dashboard");
    const periods = investorPeriods();
    preloadNavPeriodBundle(
      Object.fromEntries(periods.map((period) => [period.key, discountHistoryUrl(period)])),
      periods[0].key,
    );
  }
  if (view === "NAV-sensitivitet") {
    void loadNavSensitivityPage();
    preloadJson("/api/dashboard/summary");
    preloadJson("/api/dashboard/economic");
  }
  if (view === "Historikk") {
    void loadHistoryPage();
    preloadJson("/api/dashboard/economic");
    preloadJson(discountHistoryUrl(investorPeriods()[4]));
  }
  if (view === "Tilbakekjøpsprogram") {
    void loadBuybackPage();
    preloadJson("/api/buybacks/dashboard");
  }
  if (view === "Cash") {
    void loadCashPage();
    preloadJson("/api/dashboard/summary");
    preloadJson("/api/bemobi/dashboard");
    preloadJson("/api/dashboard/economic");
    preloadJson("/api/buybacks/dashboard");
  }
  if (view === "Bemobi") {
    void loadBemobiPage();
    preloadJson("/api/bemobi/dashboard");
    preloadJson("/api/bemobi/consensus");
  }
  if (view === "BRL/NOK") {
    void loadFxPage();
    preloadJson("/api/fx/dashboard");
    preloadJson("/api/dashboard/summary");
  }
  if (view === "Brasil") {
    void loadBrazilPage();
    preloadJson("/api/brazil/dashboard");
    preloadJson("/api/dashboard/economic");
  }
  if (view === "Konsensus") {
    void loadConsensusPage();
    preloadJson("/api/bemobi/consensus");
  }
  if (view === "Datakvalitet") {
    void loadDataQualityPage();
    preloadJson("/api/dashboard/runtime-status");
    preloadJson("/api/dashboard/report-status");
    preloadJson("/api/bemobi/source-status");
  }
  if (view === "Nyheter") {
    void loadNewsEventsPage();
    preloadJson("/api/news-events");
  }
}

function ActiveView({ view }: { view: View }) {
  if (view === "Oversikt") return <OverviewPage />;
  if (view === "NAV") return <NavPageV2 />;
  if (view === "NAV-sensitivitet") return <NavSensitivityPage />;
  if (view === "Historikk") return <EstimatedHistoryPage />;
  if (view === "Tilbakekjøpsprogram") return <BuybackPage />;
  if (view === "Cash") return <CashPage />;
  if (view === "Bemobi") {
    return <div className="normalBemobiView"><BemobiPage /></div>;
  }
  if (view === "BRL/NOK") return <FxPage />;
  if (view === "Brasil") return <BrazilPage />;
  if (view === "Konsensus") return <ConsensusPage />;
  if (view === "Nyheter") return <NewsEventsPage />;
  return <DataQualityPage />;
}

const initialView = viewFromHash(window.location.hash);
preload(initialView);

export default function InvestorApp() {
  const [activeView, setActiveView] = useState<View>(initialView);

  useEffect(() => {
    const handleHashChange = () =>
      setActiveView(viewFromHash(window.location.hash));
    window.addEventListener("hashchange", handleHashChange);
    return () => window.removeEventListener("hashchange", handleHashChange);
  }, []);

  useEffect(() => {
    document.title = `${viewTitles[activeView]} | Otello`;
  }, [activeView]);

  function selectView(view: View) {
    if (view === activeView) return;
    preload(view);
    window.location.hash = viewSlugs[view];
  }

  function skipToMain(event: MouseEvent<HTMLAnchorElement>) {
    event.preventDefault();
    document.getElementById("main-content")?.focus();
  }

  return (
    <>
      <a className="skipLink" href="#main-content" onClick={skipToMain}>
        Hopp til hovedinnhold
      </a>
      <div className="shell investorShellV2">
        <InvestorNavigation
          activeView={activeView}
          onPreload={preload}
          onSelect={selectView}
        />
        <main className="main investorMainV2" id="main-content" tabIndex={-1}>
          <ActiveInvestorView key={activeView} view={activeView} />
        </main>
      </div>
    </>
  );
}

function ActiveInvestorView({ view }: { view: View }) {
  const [pageUpdate, setPageUpdate] = useState<PageUpdate | null>(null);
  const hasUpdate = Boolean(
    pageUpdate?.timestamp
    && Number.isFinite(new Date(pageUpdate.timestamp).getTime()),
  );
  const stale = pageUpdateIsStale(pageUpdate);

  return (
    <PageUpdateProvider onUpdate={setPageUpdate}>
      <header className="investorTopbar">
        <div className="investorTopbarHeading">
          <h1>{viewTitles[view]}</h1>
          <p>{viewSubtitles[view]}</p>
        </div>
        <div className={`investorTopbarStatus${stale ? " stale" : hasUpdate ? "" : " neutral"}`}>
          <span aria-hidden="true" />
          <p>
            <strong>{pageUpdateLabel(pageUpdate?.timestamp, new Date(), pageUpdate?.label)}</strong>
            {stale ? (
              <small>{pageUpdate?.warning ?? "Dataene kan være eldre enn forventet."}</small>
            ) : !hasUpdate ? (
              <small>Venter på tidsinformasjon fra siden.</small>
            ) : null}
          </p>
        </div>
      </header>
      <Suspense fallback={<ViewFallback />}>
        <ActiveView view={view} />
      </Suspense>
    </PageUpdateProvider>
  );
}

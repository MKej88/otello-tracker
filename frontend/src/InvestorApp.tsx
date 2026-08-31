import { lazy, Suspense, useEffect, useState, type MouseEvent } from "react";
import InvestorNavigation from "./InvestorNavigation";
import { type View, viewFromHash, viewSlugs, viewTitles } from "./investorViews";
import OverviewPage from "./OverviewPage";
import { discountHistoryUrl, investorPeriods } from "./investorPeriods";
import { preloadJson } from "./navigationDataPreload";
import "./investor-v2.css";

const loadNavPage = () => import("./NavPageV2");
const loadHistoryPage = () => import("./EstimatedHistoryPage");
const loadBuybackPage = () => import("./BuybackPage");
const loadBemobiPage = () => import("./BemobiPage");
const loadBrazilPage = () => import("./BrazilPage");
const loadConsensusPage = () => import("./ConsensusPage");
const loadDataQualityPage = () => import("./DataQualityPage");
const loadNewsEventsPage = () => import("./NewsEventsPage");

const NavPageV2 = lazy(loadNavPage);
const EstimatedHistoryPage = lazy(loadHistoryPage);
const BuybackPage = lazy(loadBuybackPage);
const BemobiPage = lazy(loadBemobiPage);
const BrazilPage = lazy(loadBrazilPage);
const ConsensusPage = lazy(loadConsensusPage);
const DataQualityPage = lazy(loadDataQualityPage);
const NewsEventsPage = lazy(loadNewsEventsPage);

function ViewFallback() {
  return <section className="card viewFallback"><span className="label">VISNING</span><strong>Laster modul …</strong></section>;
}

function preload(view: View) {
  if (view === "NAV") {
    void loadNavPage();
    preloadJson(discountHistoryUrl(investorPeriods()[0]));
  }
  if (view === "Historikk") {
    void loadHistoryPage();
    preloadJson(discountHistoryUrl(investorPeriods()[4]));
  }
  if (view === "Tilbakekjøpsprogram") {
    void loadBuybackPage();
    preloadJson("/api/buybacks/dashboard");
  }
  if (view === "Bemobi") {
    void loadBemobiPage();
    preloadJson("/api/bemobi/dashboard");
  }
  if (view === "Brasil") void loadBrazilPage();
  if (view === "Konsensus") void loadConsensusPage();
  if (view === "Datakvalitet") void loadDataQualityPage();
  if (view === "Nyheter") void loadNewsEventsPage();
}

function ActiveView({ view }: { view: View }) {
  if (view === "Oversikt") return <OverviewPage />;
  if (view === "NAV") return <NavPageV2 />;
  if (view === "Historikk") return <EstimatedHistoryPage />;
  if (view === "Tilbakekjøpsprogram") return <BuybackPage />;
  if (view === "Bemobi") {
    return <div className="normalBemobiView"><BemobiPage /></div>;
  }
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
          <header className="investorTopbar">
            <h1>{viewTitles[activeView]}</h1>
          </header>
          <Suspense fallback={<ViewFallback />}>
            <ActiveView view={activeView} />
          </Suspense>
        </main>
      </div>
    </>
  );
}

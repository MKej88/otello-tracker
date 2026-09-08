import { lazy, Suspense, useEffect, useState, type MouseEvent } from "react";
import InvestorNavigation from "./InvestorNavigation";
import { type View, viewFromHash, viewSlugs, viewTitles } from "./investorViews";
import OverviewPage from "./OverviewPage";
import { discountHistoryUrl, investorPeriods } from "./investorPeriods";
import { preloadJson, preloadNavPeriodBundle } from "./navigationDataPreload";

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
const loadMethodologyPage = () => import("./MethodologyPage");

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
const MethodologyPage = lazy(loadMethodologyPage);

function ViewFallback() {
  return <section className="card viewFallback"><span className="label">VISNING</span><strong>Laster modul …</strong></section>;
}

function preload(view: View) {
  if (view === "NAV") {
    void loadNavPage();
    preloadJson("/api/dashboard/economic");
    preloadJson("/api/buybacks/dashboard");
    preloadNavPeriodBundle(Object.fromEntries(
      investorPeriods().map((period) => [period.key, discountHistoryUrl(period)]),
    ));
    // Keep the first-period preload explicit; it reuses the bundle promise and also
    // preserves a direct fallback if the nightly materialization has not run yet.
    preloadJson(discountHistoryUrl(investorPeriods()[0]));
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
    preloadJson("/api/bemobi/dashboard");
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
    preloadJson("/api/dashboard/economic");
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
  if (view === "Metode og transparens") void loadMethodologyPage();
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
  if (view === "Metode og transparens") return <MethodologyPage />;
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
          <footer className="siteFooter">
            <p>
              OtelloTracker er et uavhengig analyse- og informasjonsverktøy for
              Otello Corporation ASA og Bemobi Mobile Tech S.A. Innholdet består
              av offentlig tilgjengelige data, egne beregninger og estimater,
              og er ikke personlig investeringsrådgivning. Personen bak
              OtelloTracker har en økonomisk interesse i Otello Corporation ASA.
            </p>
            <a href="#metode">Metode og transparens</a>
          </footer>
        </main>
      </div>
    </>
  );
}

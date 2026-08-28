import { lazy, Suspense, useEffect, useState } from "react";
import OverviewPage from "./OverviewPage";
import "./investor-v2.css";

const loadNavPage = () => import("./NavPageV2");
const loadHistoryPage = () => import("./EstimatedHistoryPage");
const loadBuybackPage = () => import("./BuybackPage");
const loadBemobiPage = () => import("./BemobiPage");
const loadConsensusPage = () => import("./ConsensusPage");
const loadDataQualityPage = () => import("./DataQualityPage");
const loadNewsEventsPage = () => import("./NewsEventsPage");

const NavPageV2 = lazy(loadNavPage);
const EstimatedHistoryPage = lazy(loadHistoryPage);
const BuybackPage = lazy(loadBuybackPage);
const BemobiPage = lazy(loadBemobiPage);
const ConsensusPage = lazy(loadConsensusPage);
const DataQualityPage = lazy(loadDataQualityPage);
const NewsEventsPage = lazy(loadNewsEventsPage);

type View = "Oversikt" | "NAV" | "Historikk" | "Tilbakekjøpsprogram" | "Bemobi" | "Konsensus" | "Nyheter" | "Datakvalitet";

const menu: View[] = ["Oversikt", "NAV", "Historikk", "Tilbakekjøpsprogram", "Bemobi", "Konsensus", "Nyheter", "Datakvalitet"];
const viewSlugs: Record<View, string> = {
  Oversikt: "oversikt",
  NAV: "nav",
  Historikk: "historikk",
  Tilbakekjøpsprogram: "tilbakekjop",
  Bemobi: "bemobi",
  Konsensus: "konsensus",
  Nyheter: "nyheter",
  Datakvalitet: "datakvalitet",
};
const slugViews = Object.fromEntries(
  Object.entries(viewSlugs).map(([view, slug]) => [slug, view as View]),
) as Record<string, View>;
const titles: Record<View, string> = {
  Oversikt: "Otello investoroversikt",
  NAV: "Estimert NAV",
  Historikk: "Historisk NAV-rabatt",
  Tilbakekjøpsprogram: "Tilbakekjøpsprogram",
  Bemobi: "Bemobi",
  Konsensus: "Konsensus",
  Nyheter: "Nyheter og hendelser",
  Datakvalitet: "Datakvalitet",
};

function ViewFallback() {
  return <section className="card viewFallback"><span className="label">VISNING</span><strong>Laster modul …</strong></section>;
}

function preload(view: View) {
  if (view === "NAV") void loadNavPage();
  if (view === "Historikk") void loadHistoryPage();
  if (view === "Tilbakekjøpsprogram") void loadBuybackPage();
  if (view === "Bemobi") void loadBemobiPage();
  if (view === "Konsensus") void loadConsensusPage();
  if (view === "Datakvalitet") void loadDataQualityPage();
  if (view === "Nyheter") void loadNewsEventsPage();
}

function viewFromHash(): View {
  return slugViews[window.location.hash.slice(1).toLowerCase()] ?? "Oversikt";
}

export default function InvestorApp() {
  const [activeView, setActiveView] = useState<View>(viewFromHash);

  useEffect(() => {
    const handleHashChange = () => setActiveView(viewFromHash());
    window.addEventListener("hashchange", handleHashChange);
    return () => window.removeEventListener("hashchange", handleHashChange);
  }, []);

  function selectView(view: View) {
    setActiveView(view);
    window.history.pushState(null, "", `#${viewSlugs[view]}`);
  }

  return (
    <>
      <a className="skipLink" href="#main-content">Hopp til hovedinnhold</a>
      <div className="shell investorShellV2">
      <aside className="sidebar">
        <div className="brand"><span className="brandMark">O</span><div><strong>Otello</strong><small>Investorverktøy</small></div></div>
        <nav aria-label="Hovedmeny">
          {menu.map((item) => (
            <button
              aria-current={item === activeView ? "page" : undefined}
              className={item === activeView ? "navItem active" : "navItem"}
              key={item}
              onClick={() => selectView(item)}
              onMouseEnter={() => preload(item)}
              onFocus={() => preload(item)}
              type="button"
            >
              <span aria-hidden="true" className="navDot" />{item}
            </button>
          ))}
        </nav>
        <div className="sidebarFooter investorSidebarFooter">Teknisk status ligger under Datakvalitet</div>
      </aside>
      <main className="main investorMainV2" id="main-content">
        <header className="investorTopbar">
          <div><p className="eyebrow">OTELLO / BEMOBI</p><h1>{titles[activeView]}</h1></div>
          {activeView !== "Datakvalitet" && <span className="investorModelBadge">ESTIMERT NAV</span>}
        </header>
        <Suspense fallback={<ViewFallback />}>
          {activeView === "Oversikt" ? <OverviewPage />
            : activeView === "NAV" ? <NavPageV2 />
              : activeView === "Historikk" ? <EstimatedHistoryPage />
                : activeView === "Tilbakekjøpsprogram" ? <BuybackPage />
                  : activeView === "Bemobi" ? <div className="normalBemobiView"><BemobiPage /></div>
                    : activeView === "Konsensus" ? <ConsensusPage />
                      : activeView === "Nyheter" ? <NewsEventsPage />
                        : <DataQualityPage />}
        </Suspense>
      </main>
      </div>
    </>
  );
}

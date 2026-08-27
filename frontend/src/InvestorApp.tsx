import { lazy, Suspense, useState } from "react";
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

export default function InvestorApp() {
  const [activeView, setActiveView] = useState<View>("Oversikt");
  return (
    <div className="shell investorShellV2">
      <aside className="sidebar">
        <div className="brand"><span className="brandMark">O</span><div><strong>Otello</strong><small>Investorverktøy</small></div></div>
        <nav>
          {menu.map((item) => (
            <button className={item === activeView ? "navItem active" : "navItem"} key={item} onClick={() => setActiveView(item)} onMouseEnter={() => preload(item)} onFocus={() => preload(item)} type="button">
              <span className="navDot" />{item}
            </button>
          ))}
        </nav>
        <div className="sidebarFooter investorSidebarFooter">Teknisk status ligger under Datakvalitet</div>
      </aside>
      <main className="main investorMainV2">
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
  );
}

import { lazy, Suspense, useState } from "react";
import OverviewPage from "./OverviewPage";
import NavPageV2 from "./NavPageV2";
import EstimatedHistoryPage from "./EstimatedHistoryPage";
import DataQualityPage from "./DataQualityPage";
import "./investor-v2.css";

const loadBuybackPage = () => import("./BuybackPage");
const loadBemobiPage = () => import("./BemobiPage");
const loadConsensusPage = () => import("./ConsensusPage");

const BuybackPage = lazy(loadBuybackPage);
const BemobiPage = lazy(loadBemobiPage);
const ConsensusPage = lazy(loadConsensusPage);

type View = "Oversikt" | "NAV" | "Historikk" | "Tilbakekjøp" | "Bemobi" | "Konsensus" | "Datakvalitet";

const menu: View[] = ["Oversikt", "NAV", "Historikk", "Tilbakekjøp", "Bemobi", "Konsensus", "Datakvalitet"];
const titles: Record<View, string> = {
  Oversikt: "Otello investoroversikt",
  NAV: "Estimert NAV",
  Historikk: "Historisk NAV-rabatt",
  Tilbakekjøp: "Tilbakekjøp",
  Bemobi: "Bemobi",
  Konsensus: "Konsensus",
  Datakvalitet: "Datakvalitet",
};

function ViewFallback() {
  return <section className="card viewFallback"><span className="label">VISNING</span><strong>Laster modul …</strong></section>;
}

function preload(view: View) {
  if (view === "Tilbakekjøp") void loadBuybackPage();
  if (view === "Bemobi") void loadBemobiPage();
  if (view === "Konsensus") void loadConsensusPage();
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
        {activeView === "Oversikt" ? <OverviewPage />
          : activeView === "NAV" ? <NavPageV2 />
            : activeView === "Historikk" ? <EstimatedHistoryPage />
              : activeView === "Tilbakekjøp" ? <Suspense fallback={<ViewFallback />}><BuybackPage /></Suspense>
                : activeView === "Bemobi" ? <div className="normalBemobiView"><Suspense fallback={<ViewFallback />}><BemobiPage /></Suspense></div>
                  : activeView === "Konsensus" ? <Suspense fallback={<ViewFallback />}><ConsensusPage /></Suspense>
                    : <DataQualityPage />}
      </main>
    </div>
  );
}

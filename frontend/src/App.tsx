import { useEffect, useState } from "react";

type Summary = {
  nav_per_share: number;
  otec_price: number;
  nav_discount_pct: number;
  bmob3_price: number;
  brl_nok: number;
  estimated_cash_mnok: number;
  data_status: string;
};

const fallback: Summary = {
  nav_per_share: 24.82,
  otec_price: 17.2,
  nav_discount_pct: 30.7,
  bmob3_price: 31.2,
  brl_nok: 1.72,
  estimated_cash_mnok: 112.4,
  data_status: "demo"
};

const menu = [
  "Oversikt",
  "NAV",
  "Historikk",
  "Tilbakekjøp",
  "Bemobi",
  "Consensus",
  "Aksjonærer",
  "Nyheter",
  "Innstillinger"
];

export default function App() {
  const [summary, setSummary] = useState<Summary>(fallback);
  const [apiOk, setApiOk] = useState(false);

  useEffect(() => {
    fetch("/api/dashboard/summary")
      .then((r) => {
        if (!r.ok) throw new Error("API-feil");
        return r.json();
      })
      .then((data: Summary) => {
        setSummary(data);
        setApiOk(true);
      })
      .catch(() => setApiOk(false));
  }, []);

  const cards = [
    ["NAV/aksje", `${summary.nav_per_share.toFixed(2)} kr`, "+1,72 %", "positive"],
    ["OTEC kurs", `${summary.otec_price.toFixed(2)} kr`, "-0,86 %", "negative"],
    ["Rabatt til NAV", `${summary.nav_discount_pct.toFixed(1)} %`, "-0,6 pp", "positive"],
    ["BMOB3", `R$ ${summary.bmob3_price.toFixed(2)}`, "+2,80 %", "positive"],
    ["BRL/NOK", summary.brl_nok.toFixed(2), "+0,58 %", "positive"],
    ["Estimert cash", `${summary.estimated_cash_mnok.toFixed(1)}m`, "+6,03 %", "positive"]
  ];

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brandMark">O</span>
          <div>
            <strong>Otello</strong>
            <small>Investorverktøy</small>
          </div>
        </div>

        <nav>
          {menu.map((item, index) => (
            <button className={index === 0 ? "navItem active" : "navItem"} key={item}>
              <span className="navDot" />
              {item}
            </button>
          ))}
        </nav>

        <div className="sidebarFooter">
          <span className={apiOk ? "statusDot ok" : "statusDot"} />
          API {apiOk ? "tilkoblet" : "venter"}
        </div>
      </aside>

      <main className="main">
        <header>
          <div>
            <p className="eyebrow">OTELLO / BEMOBI</p>
            <h1>Otello NAV Dashboard</h1>
          </div>
          <div className="updated">
            <span className={apiOk ? "statusDot ok" : "statusDot"} />
            Fase 1 · demo-data
          </div>
        </header>

        <section className="kpiGrid">
          {cards.map(([label, value, change, tone]) => (
            <article className="card kpi" key={label}>
              <span className="label">{label}</span>
              <strong>{value}</strong>
              <span className={`change ${tone}`}>{change}</span>
              <div className={`spark ${tone}`} />
            </article>
          ))}
        </section>

        <section className="chartGrid">
          <article className="card chart">
            <div className="cardHeader">
              <div>
                <span className="label">Markeds-NAV</span>
                <h2>NAV vs OTEC</h2>
              </div>
              <span className="pill">1 ÅR</span>
            </div>
            <div className="fakeChart">
              <div className="line navLine" />
              <div className="line priceLine" />
              <span className="chartCaption">Datakobling bygges i fase 2–4</span>
            </div>
          </article>

          <article className="card chart">
            <div className="cardHeader">
              <div>
                <span className="label">Verdsettelse</span>
                <h2>Historisk NAV-rabatt</h2>
              </div>
              <span className="pill">30,7 %</span>
            </div>
            <div className="discountChart">
              <div className="discountArea" />
              <div className="averageLine" />
              <span className="chartCaption">Historikken fylles når NAV-motoren er klar</span>
            </div>
          </article>
        </section>

        <section className="lowerGrid">
          <article className="card">
            <div className="cardHeader">
              <div>
                <span className="label">Kapitalallokering</span>
                <h2>Tilbakekjøp</h2>
              </div>
              <span className="pill muted">Neste modul</span>
            </div>
            <div className="placeholderRows">
              <div><span>Siste kjøp</span><strong>–</strong></div>
              <div><span>Egne aksjer</span><strong>–</strong></div>
              <div><span>Akkretiv effekt</span><strong>–</strong></div>
            </div>
          </article>

          <article className="card">
            <div className="cardHeader">
              <div>
                <span className="label">Underliggende verdi</span>
                <h2>Bemobi-eksponering</h2>
              </div>
            </div>
            <div className="exposure">
              <div className="donut"><span>38,22%</span></div>
              <div className="placeholderRows grow">
                <div><span>BMOB3-aksjer</span><strong>32 719 588</strong></div>
                <div><span>BMOB3-kurs</span><strong>R$ {summary.bmob3_price.toFixed(2)}</strong></div>
              </div>
            </div>
          </article>

          <article className="card">
            <div className="cardHeader">
              <div>
                <span className="label">System</span>
                <h2>Modellstatus</h2>
              </div>
            </div>
            <div className="sourceList">
              {["FastAPI", "Frontend", "Docker-oppsett", "GitHub CI"].map((source) => (
                <div key={source}>
                  <span>{source}</span>
                  <span className="sourceOk">KLAR</span>
                </div>
              ))}
            </div>
          </article>
        </section>
      </main>
    </div>
  );
}

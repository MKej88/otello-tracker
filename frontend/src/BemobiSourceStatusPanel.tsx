import { useEffect, useMemo, useState } from "react";
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

type CvmQuarter = {
  period?: string | null;
  reported_revenue_mbrl?: number | null;
  reported_ebit_mbrl?: number | null;
  reported_net_income_parent_mbrl?: number | null;
  reported_operating_cash_flow_mbrl?: number | null;
  reported_capex_cash_outflow_mbrl?: number | null;
  reported_cash_mbrl?: number | null;
  reported_borrowings_current_mbrl?: number | null;
  reported_borrowings_noncurrent_mbrl?: number | null;
  reported_borrowings_mbrl?: number | null;
  reported_net_debt_mbrl?: number | null;
};

type BemobiDashboard = {
  valuation?: {
    source_quarters?: CvmQuarter[];
  };
};

const AUTO_REFRESH_MS = 2 * 60 * 1000;

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

function numberValue(input: number | null | undefined, digits = 1) {
  if (input == null || !Number.isFinite(input)) return "–";
  return input.toLocaleString("nb-NO", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits
  });
}

function completeTtm(quarters: CvmQuarter[], field: keyof CvmQuarter) {
  if (quarters.length !== 4) return null;
  const values = quarters.map((quarter) => quarter[field]);
  if (values.some((value) => typeof value !== "number" || !Number.isFinite(value))) return null;
  return values.reduce<number>((sum, value) => sum + Number(value), 0);
}

function CvmAccountingSnapshot({ quarters }: { quarters: CvmQuarter[] }) {
  const latest = quarters.at(-1);
  const revenueTtm = completeTtm(quarters, "reported_revenue_mbrl");
  const ebitTtm = completeTtm(quarters, "reported_ebit_mbrl");
  const netIncomeTtm = completeTtm(quarters, "reported_net_income_parent_mbrl");
  const operatingCashFlowTtm = completeTtm(quarters, "reported_operating_cash_flow_mbrl");
  const capexCashOutflowTtm = completeTtm(quarters, "reported_capex_cash_outflow_mbrl");
  const capexTtm = capexCashOutflowTtm == null ? null : Math.abs(capexCashOutflowTtm);
  const fcfTtm = operatingCashFlowTtm == null || capexTtm == null
    ? null
    : operatingCashFlowTtm - capexTtm;
  const netDebt = latest?.reported_net_debt_mbrl;
  const netCash = typeof netDebt === "number" ? -netDebt : null;
  const ready = [revenueTtm, ebitTtm, netIncomeTtm, operatingCashFlowTtm].some(
    (value) => value != null
  );

  return (
    <div className="bemobiSourceCvmSnapshot">
      <div className="cardHeader">
        <div>
          <span className="label">CVM-REGNSKAP</span>
          <h2>Standardisert kontrollgrunnlag</h2>
        </div>
        <span className="pill muted">{latest?.period ?? "VENTER"}</span>
      </div>

      {ready ? (
        <div className="placeholderRows">
          <div><span>Rapportert omsetning TTM · konto 3.01</span><strong>R$ {numberValue(revenueTtm)}m</strong></div>
          <div><span>Rapportert EBIT TTM · konto 3.05</span><strong>R$ {numberValue(ebitTtm)}m</strong></div>
          <div><span>Resultat til Bemobi-aksjonærer TTM · 3.11.01</span><strong>R$ {numberValue(netIncomeTtm)}m</strong></div>
          <div><span>Operasjonell kontantstrøm TTM · 6.01</span><strong>R$ {numberValue(operatingCashFlowTtm)}m</strong></div>
          <div><span>Capex TTM · 6.02.02</span><strong>R$ {numberValue(capexTtm)}m</strong></div>
          <div><span>FCF TTM · CFO minus capex</span><strong>R$ {numberValue(fcfTtm)}m</strong></div>
          <div><span>Kontanter ved kvartalsslutt · 1.01.01</span><strong>R$ {numberValue(latest?.reported_cash_mbrl)}m</strong></div>
          <div><span>Lånegjeld ved kvartalsslutt</span><strong>R$ {numberValue(latest?.reported_borrowings_mbrl)}m</strong></div>
          <div><span>Netto kontant (CVM-lånegjeld minus kontanter)</span><strong>R$ {numberValue(netCash)}m</strong></div>
        </div>
      ) : (
        <p className="bemobiFootnote">
          Venter på første komplette CVM ITR/DFP-refresh for de standardiserte regnskapstallene.
        </p>
      )}

      <p className="bemobiFootnote">
        Dette er standardiserte, konsoliderte CVM-regnskapstall. Capex fra 6.02.02 brukes som
        regulatorisk avstemming; Bemobis justerte capex kan ha et annet omfang. Justerte KPI-er som
        justert EBITDA og justert resultat beholdes derfor fra Bemobis offisielle resultatdokument.
      </p>
    </div>
  );
}

export default function BemobiSourceStatusPanel() {
  const [data, setData] = useState<SourceStatus | null>(null);
  const [failed, setFailed] = useState(false);
  const [cvmQuarters, setCvmQuarters] = useState<CvmQuarter[]>([]);

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
    const loadCvm = () => {
      fetch("/api/bemobi/dashboard")
        .then((response) => {
          if (!response.ok) throw new Error("Bemobi dashboard API-feil");
          return response.json() as Promise<BemobiDashboard>;
        })
        .then((result) => {
          if (!active) return;
          setCvmQuarters((result.valuation?.source_quarters ?? []).slice(-4));
        })
        .catch(() => {
          if (!active) return;
          setCvmQuarters([]);
        });
    };

    loadStatus();
    loadCvm();
    const timer = window.setInterval(() => {
      loadStatus();
      loadCvm();
    }, AUTO_REFRESH_MS);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  const snapshot = useMemo(() => cvmQuarters.slice(-4), [cvmQuarters]);

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
          <span>Data</span><span>Kilde</span><span>Status</span><span>Sist hentet</span><span>Sist kontrollert</span>
        </div>
        {(data.items ?? []).map((item) => (
          <div className="sourceStatusRow" key={item.key}>
            <span className="sourceStatusName"><strong>{item.label}</strong><small>Datadato {dateLabel(item.data_date)}</small></span>
            <span className="sourceStatusSource">
              {item.url ? (
                <a href={item.url} target="_blank" rel="noreferrer">
                  {item.source} ↗
                </a>
              ) : (
                item.source
              )}
            </span>
            <span><strong className={`sourceStatusBadge sourceStatus-${item.status.toLowerCase()}`}>{statusLabel(item.status)}</strong>{item.uses_last_good && <small>Bruker siste gode verdi</small>}</span>
            <span><b className="mobileSourceLabel">Sist hentet</b>{dateTimeLabel(item.last_good_at)}</span>
            <span><b className="mobileSourceLabel">Sist kontrollert</b>{dateTimeLabel(item.checked_at)}</span>
            {item.detail && <small className="sourceStatusDetail">{item.detail}</small>}
          </div>
        ))}
      </div>

      <p className="bemobiFootnote">
        Offisielle kilder prioriteres. Hvis MarketScreener eller en annen sekundær kilde feiler,
        beholdes siste validerte verdi i stedet for å nullstille eller erstatte den med usikre data.
      </p>

      <CvmAccountingSnapshot quarters={snapshot} />
    </section>
  );
}

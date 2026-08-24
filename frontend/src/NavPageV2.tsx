import { useEffect, useMemo, useState } from "react";
import { investorPeriods, type InvestorPeriod } from "./investorPeriods";
import { usePollingResource } from "./usePollingResource";

const REFRESH_MS = 2 * 60 * 1000;

type Composition = {
  key: string;
  label: string;
  amount_mnok: number;
  per_share_nok: number;
  formula?: string;
  details?: Record<string, unknown>;
};

type Driver = {
  key: string;
  label: string;
  per_share_nok: number;
  start_per_share_nok: number;
  current_per_share_nok: number;
};

type EstimatedHistory = {
  ready: boolean;
  from?: string;
  to?: string;
  current?: {
    date: string;
    nav_total_mnok: number;
    nav_per_share: number;
    discount_pct?: number | null;
    composition?: Composition[];
    reconciliation_residual_mnok?: number;
  };
  change?: {
    ready: boolean;
    requested_start?: string;
    resolved_start?: string;
    current_date?: string;
    start_nav_per_share?: number;
    current_nav_per_share?: number;
    change_per_share_nok?: number;
    drivers?: Driver[];
    reconciliation_residual_nok?: number;
  };
};

type Payload = { estimated?: EstimatedHistory };
type EstimatedNav = { ready: boolean; as_of_date?: string; nav_per_share?: number | null; discount_pct?: number | null };

function value(input?: number | null, digits = 2) {
  if (input == null || !Number.isFinite(input)) return "–";
  return input.toLocaleString("nb-NO", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function signed(input?: number | null, digits = 2) {
  if (input == null || !Number.isFinite(input)) return "–";
  return `${input > 0 ? "+" : ""}${value(input, digits)}`;
}

function dateLabel(input?: string | null) {
  if (!input) return "–";
  const [year, month, day] = input.slice(0, 10).split("-");
  return year && month && day ? `${day}.${month}.${year}` : input;
}

function PeriodButtons({ selected, onChange }: { selected: InvestorPeriod; onChange: (period: InvestorPeriod) => void }) {
  return (
    <div className="periodButtons" aria-label="Velg periode">
      {investorPeriods().map((period) => (
        <button className={period.key === selected.key ? "active" : ""} key={period.key} onClick={() => onChange(period)} type="button">
          {period.label}
        </button>
      ))}
    </div>
  );
}

export default function NavPageV2() {
  const periods = useMemo(() => investorPeriods(), []);
  const [period, setPeriod] = useState(periods[0]);
  const [cache, setCache] = useState<Record<string, EstimatedHistory>>({});
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const { data: live } = usePollingResource<EstimatedNav>("/api/dashboard/economic", REFRESH_MS);
  const data = cache[period.key];

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    const load = async () => {
      setLoading(true);
      try {
        const response = await fetch(`/api/dashboard/discount-history?days=${period.days}&max_points=72`, { signal: controller.signal });
        if (!response.ok) throw new Error("NAV-historikk feilet");
        const payload = await response.json() as Payload;
        if (!active) return;
        if (payload.estimated) setCache((current) => ({ ...current, [period.key]: payload.estimated! }));
        setFailed(false);
      } catch (error) {
        if (!active || (error instanceof DOMException && error.name === "AbortError")) return;
        setFailed(true);
      } finally {
        if (active) setLoading(false);
      }
    };
    void load();
    return () => { active = false; controller.abort(); };
  }, [period.key, period.days]);

  const current = data?.current;
  const change = data?.change;
  const components = current?.composition ?? [];
  const maxDriver = Math.max(0.01, ...(change?.drivers ?? []).map((item) => Math.abs(item.per_share_nok)));

  return (
    <div className="investorPage navV2">
      <section className="estimatedHero card">
        <div>
          <span className="label">ESTIMERT NAV</span>
          <h2>{live?.ready ? `${value(live.nav_per_share)} kr per aksje` : "Laster …"}</h2>
          <p>Dette er NAV-en som brukes i investorvisningen. Under ser du nøyaktig hvilke verdier som bygger den opp.</p>
        </div>
        <div className="estimatedHeroSide">
          <div><span>Rabatt</span><strong>{value(live?.discount_pct, 1)} %</strong></div>
          <small>Datadato {dateLabel(live?.as_of_date)}</small>
        </div>
      </section>

      <section className="card compositionCard">
        <div className="cardHeader">
          <div><span className="label">SAMMENSETNING</span><h2>Hva består Estimert NAV av i dag?</h2></div>
          <span className="pill">{dateLabel(current?.date ?? live?.as_of_date)}</span>
        </div>
        {loading && !data && <p className="dataNotice">Beregner sammensetningen …</p>}
        {failed && !data && <p className="dataNotice">Kunne ikke hente NAV-sammensetningen.</p>}
        {data && !data.ready && <p className="dataNotice">Historisk Estimert NAV er ikke komplett nok ennå.</p>}
        {components.length > 0 && (
          <div className="compositionTable">
            <div className="compositionHead"><span>Komponent</span><span>Verdi</span><span>Per aksje</span><span>Beregning</span></div>
            {components.map((item) => (
              <div className="compositionRow" key={item.key}>
                <strong>{item.label}</strong>
                <span>{value(item.amount_mnok, 1)} mill. kr</span>
                <span className={item.per_share_nok < 0 ? "negative" : ""}>{value(item.per_share_nok)} kr</span>
                <small>{item.formula}</small>
              </div>
            ))}
            <div className="compositionTotal">
              <strong>Estimert NAV</strong>
              <span>{value(current?.nav_total_mnok, 1)} mill. kr</span>
              <span>{value(current?.nav_per_share)} kr</span>
              <small>Sum av komponentene over</small>
            </div>
          </div>
        )}
      </section>

      <section className="card navDriversCard">
        <div className="cardHeader driverHeader">
          <div><span className="label">ENDRING</span><h2>Hva har flyttet Estimert NAV?</h2></div>
          <PeriodButtons selected={period} onChange={setPeriod} />
        </div>
        {loading && data && <div className="inlineLoading">Oppdaterer periode …</div>}
        {change?.ready ? (
          <>
            <div className="changeSummary">
              <div><span>Fra</span><strong>{value(change.start_nav_per_share)} kr</strong><small>{dateLabel(change.resolved_start)}</small></div>
              <div><span>Til</span><strong>{value(change.current_nav_per_share)} kr</strong><small>{dateLabel(change.current_date)}</small></div>
              <div><span>Endring</span><strong className={(change.change_per_share_nok ?? 0) >= 0 ? "positive" : "negative"}>{signed(change.change_per_share_nok)} kr</strong><small>per aksje</small></div>
            </div>
            <div className="driverList">
              {(change.drivers ?? []).map((driver) => {
                const width = Math.max(2, Math.abs(driver.per_share_nok) / maxDriver * 100);
                return (
                  <div className="driverRow" key={driver.key}>
                    <span>{driver.label}</span>
                    <div className="driverBarTrack"><div className={`driverBar ${driver.per_share_nok >= 0 ? "positiveBar" : "negativeBar"}`} style={{ width: `${width}%` }} /></div>
                    <strong className={driver.per_share_nok >= 0 ? "positive" : "negative"}>{signed(driver.per_share_nok)} kr</strong>
                  </div>
                );
              })}
            </div>
            <p className="methodNote">Perioden bruker nærmeste tilgjengelige kildebelagte Estimert NAV-observasjon ved start og avstemmer komponentendringene til total endring per aksje.</p>
          </>
        ) : (
          <p className="dataNotice">Venter på nok historiske Estimert NAV-observasjoner for valgt periode.</p>
        )}
      </section>
    </div>
  );
}

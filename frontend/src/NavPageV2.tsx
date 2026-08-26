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
  amount_mnok?: number | null;
  impact_kind?: string;
  start_per_share_nok?: number | null;
  current_per_share_nok?: number | null;
  details?: Record<string, unknown>;
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
    attribution_method?: string;
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

function detailNumber(driver: Driver, key: string) {
  const raw = driver.details?.[key];
  return typeof raw === "number" && Number.isFinite(raw) ? raw : null;
}

function displayAvailable(details?: Record<string, unknown>) {
  return details?.display_available !== false;
}

function driverMovement(driver: Driver) {
  if (driver.key === "life360" && !displayAvailable(driver.details)) {
    return "Datagrunnlag mangler";
  }
  switch (driver.key) {
    case "bemobi_price":
      return `R$ ${value(detailNumber(driver, "start_price_brl"))} → R$ ${value(detailNumber(driver, "current_price_brl"))}`;
    case "bemobi_fx":
      return `BRL/NOK ${value(detailNumber(driver, "start_brl_nok"), 4)} → ${value(detailNumber(driver, "current_brl_nok"), 4)}`;
    case "bemobi_receivable":
      return `${value(detailNumber(driver, "start_mnok"), 1)} → ${value(detailNumber(driver, "current_mnok"), 1)} mill. kr til gode`;
    case "bemobi_paid": {
      const gross = detailNumber(driver, "gross_mnok");
      const withholding = detailNumber(driver, "withholding_mnok");
      const net = detailNumber(driver, "net_mnok");
      if (gross != null && withholding != null) {
        return `Netto ${signed(net, 1)} mill. kr (brutto ${signed(gross, 1)}, skatt ${signed(withholding, 1)})`;
      }
      return `Netto ${signed(net, 1)} mill. kr mottatt`;
    }
    case "buyback_cash":
      return `${signed(detailNumber(driver, "cash_mnok"), 1)} mill. kr cash`;
    case "buyback_shares": {
      const start = detailNumber(driver, "start_shares");
      const current = detailNumber(driver, "current_shares");
      const reduced = detailNumber(driver, "shares_reduced");
      return `${value(start == null ? null : start / 1_000_000, 2)} → ${value(current == null ? null : current / 1_000_000, 2)} mill. aksjer (${value(reduced, 0)} færre)`;
    }
    case "other_cash":
    case "other_ona":
    case "life360":
    case "options": {
      const start = detailNumber(driver, "start_amount_mnok");
      const current = detailNumber(driver, "current_amount_mnok");
      if (start != null && current != null) return `${value(start, 1)} → ${value(current, 1)} mill. kr`;
      return `${signed(driver.amount_mnok, 1)} mill. kr`;
    }
    case "model_residual":
      return "Avstemming mellom underkomponenter og total NAV";
    default:
      return driver.amount_mnok == null ? "–" : `${signed(driver.amount_mnok, 1)} mill. kr`;
  }
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
            {components.map((item) => {
              const available = item.key !== "life360" || displayAvailable(item.details);
              return (
                <div className="compositionRow" key={item.key}>
                  <strong>{item.label}</strong>
                  <span>{available ? `${value(item.amount_mnok, 1)} mill. kr` : "–"}</span>
                  <span className={available && item.per_share_nok < 0 ? "negative" : ""}>{available ? `${value(item.per_share_nok)} kr` : "–"}</span>
                  <small>{available ? item.formula : "Mangler gyldig LIF-kurs og rapportanker"}</small>
                </div>
              );
            })}
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
              <div><span>Nettoendring</span><strong className={(change.change_per_share_nok ?? 0) >= 0 ? "positive" : "negative"}>{signed(change.change_per_share_nok)} kr</strong><small>per aksje</small></div>
            </div>
            <div className="compositionTable driverNetTable">
              <div className="compositionHead"><span>Komponent</span><span>Bevegelse</span><span>Verdieffekt</span><span>Nettoeffekt NAV/aksje</span></div>
              {(change.drivers ?? []).map((driver) => {
                const available = driver.key !== "life360" || displayAvailable(driver.details);
                return (
                  <div className="compositionRow" key={driver.key}>
                    <strong>{driver.label}</strong>
                    <span>{driverMovement(driver)}</span>
                    <span className={available ? ((driver.amount_mnok ?? 0) >= 0 ? "positive" : "negative") : ""}>{available ? (driver.amount_mnok == null ? "–" : `${signed(driver.amount_mnok, 1)} mill. kr`) : "–"}</span>
                    <span className={available ? (driver.per_share_nok >= 0 ? "positive" : "negative") : ""}>{available ? `${signed(driver.per_share_nok)} kr/aksje` : "–"}</span>
                  </div>
                );
              })}
              <div className="compositionTotal">
                <strong>Estimert NAV</strong>
                <span>{dateLabel(change.resolved_start)} → {dateLabel(change.current_date)}</span>
                <span>–</span>
                <span className={(change.change_per_share_nok ?? 0) >= 0 ? "positive" : "negative"}>{signed(change.change_per_share_nok)} kr/aksje</span>
              </div>
            </div>
            <p className="methodNote">Bemobi deles i aksjekurs, BRL/NOK, tilgode utbytte/JCP og faktisk utbetalt utbytte/JCP. Tilbakekjøp vises som to egne effekter: kontantbruk og færre utestående aksjer. NAV/aksje-effekten fordeles symmetrisk mellom verdiendring og aksjeantall, slik at kryssleddet ikke avhenger av rekkefølgen og summen fortsatt avstemmer mot nettoendringen i Estimert NAV.</p>
          </>
        ) : (
          <p className="dataNotice">Venter på nok historiske Estimert NAV-observasjoner for valgt periode.</p>
        )}
      </section>
    </div>
  );
}
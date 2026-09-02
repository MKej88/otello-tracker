import { useEffect, useMemo, useState } from "react";
import { discountHistoryUrl, investorPeriods, type InvestorPeriod } from "./investorPeriods";
import { fetchPreloadedJson } from "./navigationDataPreload";
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

type DriverBreakdown = {
  label: string;
  movement: string;
  amount_mnok?: number | null;
  per_share_nok: number;
};

type DisplayDriver = Driver & { breakdown?: DriverBreakdown[] };

type EstimatedHistory = {
  ready: boolean;
  from?: string;
  to?: string;
  current?: {
    date: string;
    nav_total_mnok: number;
    nav_per_share: number;
    discount_pct?: number | null;
    shares_outstanding?: number | null;
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
type EstimatedNav = {
  ready: boolean;
  as_of_date?: string;
  calculated_at?: string | null;
  nav_per_share?: number | null;
  discount_pct?: number | null;
  shares_outstanding?: number | null;
};

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

function dateTimeLabel(input?: string | null) {
  if (!input) return "–";
  const parsed = new Date(input);
  if (!Number.isFinite(parsed.getTime())) return input;
  return parsed.toLocaleString("nb-NO", {
    day: "2-digit", month: "2-digit", year: "numeric",
    hour: "2-digit", minute: "2-digit", timeZone: "Europe/Oslo",
  });
}

function integer(input?: number | null) {
  if (input == null || !Number.isFinite(input)) return "–";
  return Math.round(input).toLocaleString("nb-NO");
}

function detailNumber(driver: Driver, key: string) {
  const raw = driver.details?.[key];
  return typeof raw === "number" && Number.isFinite(raw) ? raw : null;
}

function compositionDetailNumber(item: Composition | undefined, key: string) {
  const raw = item?.details?.[key];
  return typeof raw === "number" && Number.isFinite(raw) ? raw : null;
}

function compositionWithoutSeparateFxRow(components: Composition[]) {
  const fx = components.find((item) => item.key === "fx_since_report");
  if (!fx) return components;

  const cashFx = compositionDetailNumber(fx, "cash_fx_mnok");
  const investmentFx = compositionDetailNumber(fx, "investment_fx_mnok");
  const cash = components.find((item) => item.key === "reported_cash");
  const residual = components.find((item) => item.key === "other_reported_assets_liabilities");

  // Alliance Venture Spring AS is a Norwegian AS and its NOK fair value is fixed
  // at the latest report. Never allocate running USD/NOK effects to Alliance.
  if (cashFx == null || investmentFx == null) return components;
  if (Math.abs(cashFx) > 1e-9 && !cash) return components;
  if (Math.abs(investmentFx) > 1e-9 && !residual) return components;

  const fxPerShare = (extraM: number) => (
    Math.abs(fx.amount_mnok) > 1e-12 ? fx.per_share_nok * (extraM / fx.amount_mnok) : 0
  );

  return components
    .filter((item) => item.key !== "fx_since_report")
    .map((item) => {
      let embeddedFx = 0;
      let formula = item.formula;

      if (item.key === "reported_cash") {
        embeddedFx = cashFx;
        if (Math.abs(embeddedFx) > 1e-9) {
          formula = `${item.formula ?? "Siste rapporterte kontantbeholdning"} + valutaeffekt på dokumentert valutaeksponering`;
        }
      } else if (item.key === "other_reported_assets_liabilities") {
        embeddedFx = investmentFx;
        if (Math.abs(embeddedFx) > 1e-9) {
          formula = "Rapportert verdi fra siste rapport";
        }
      }

      if (Math.abs(embeddedFx) <= 1e-9) return item;
      return {
        ...item,
        amount_mnok: item.amount_mnok + embeddedFx,
        per_share_nok: item.per_share_nok + fxPerShare(embeddedFx),
        formula,
        details: { ...item.details, display_fx_embedded_mnok: embeddedFx },
      };
    });
}

function sortCompositionByValue(components: Composition[]) {
  return [...components].sort((left, right) => right.amount_mnok - left.amount_mnok);
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

function groupedDrivers(drivers: Driver[]): DisplayDriver[] {
  const bemobiPrice = drivers.find((driver) => driver.key === "bemobi_price");
  const bemobiFx = drivers.find((driver) => driver.key === "bemobi_fx");
  const bemobiReceivable = drivers.find((driver) => driver.key === "bemobi_receivable");
  const bemobiPaid = drivers.find((driver) => driver.key === "bemobi_paid");
  const buybackCash = drivers.find((driver) => driver.key === "buyback_cash");
  const buybackShares = drivers.find((driver) => driver.key === "buyback_shares");
  const groupedKeys = new Set<string>();
  const result: DisplayDriver[] = [];

  const addGroup = (
    key: string,
    label: string,
    parts: Driver[],
  ) => {
    parts.forEach((part) => groupedKeys.add(part.key));
    result.push({
      key,
      label,
      amount_mnok: parts.every((part) => part.amount_mnok == null)
        ? null
        : parts.reduce((sum, part) => sum + (part.amount_mnok ?? 0), 0),
      per_share_nok: parts.reduce((sum, part) => sum + part.per_share_nok, 0),
      breakdown: parts.map((part) => ({
        label: part.key === "bemobi_price"
          ? "Aksjekurs"
          : part.key === "bemobi_fx"
            ? "Valuta (BRL/NOK)"
            : part.key === "buyback_cash"
              ? "Kontantbruk"
              : "Færre aksjer",
        movement: driverMovement(part),
        amount_mnok: part.amount_mnok,
        per_share_nok: part.per_share_nok,
      })),
    });
  };

  if (bemobiPrice && bemobiFx) {
    addGroup("bemobi_net", "Bemobi – netto", [bemobiPrice, bemobiFx]);
  }
  if (bemobiReceivable || bemobiPaid) {
    const parts = [bemobiReceivable, bemobiPaid].filter((part): part is Driver => part != null);
    parts.forEach((part) => groupedKeys.add(part.key));
    result.push({
      key: "bemobi_confirmed_cash",
      label: "Bemobi-utbetalinger",
      amount_mnok: parts.reduce((sum, part) => sum + (part.amount_mnok ?? 0), 0),
      per_share_nok: parts.reduce((sum, part) => sum + part.per_share_nok, 0),
      breakdown: parts.map((part) => ({
        label: part.key === "bemobi_receivable" ? "Fordring" : "Utbetalt",
        movement: driverMovement(part),
        amount_mnok: part.amount_mnok,
        per_share_nok: part.per_share_nok,
      })),
    });
  }
  if (buybackCash && buybackShares) {
    addGroup("buyback_net", "Tilbakekjøp – netto", [buybackCash, buybackShares]);
  }

  for (const driver of drivers) {
    if (groupedKeys.has(driver.key)) continue;
    if (driver.key === "life360") {
      const priceEffect = detailNumber(driver, "price_effect_per_share_nok");
      const fxEffect = detailNumber(driver, "fx_effect_per_share_nok");
      result.push({
        ...driver,
        label: "Life 360",
        breakdown: priceEffect == null || fxEffect == null ? undefined : [
          {
            label: "Aksjekurs",
            movement: `USD ${value(detailNumber(driver, "start_price_usd"))} → USD ${value(detailNumber(driver, "current_price_usd"))}`,
            amount_mnok: detailNumber(driver, "price_effect_mnok"),
            per_share_nok: priceEffect,
          },
          {
            label: "Valuta (USD/NOK)",
            movement: `USD/NOK ${value(detailNumber(driver, "start_usd_nok"), 4)} → ${value(detailNumber(driver, "current_usd_nok"), 4)}`,
            amount_mnok: detailNumber(driver, "fx_effect_mnok"),
            per_share_nok: fxEffect,
          },
        ],
      });
      continue;
    }
    if (driver.key === "other_cash") {
      const operatingCost = detailNumber(driver, "operating_cost_mnok");
      const interestIncome = detailNumber(driver, "interest_income_mnok");
      const otherMovements = detailNumber(driver, "other_movements_mnok");
      const scale = driver.amount_mnok ? driver.per_share_nok / driver.amount_mnok : 0;
      const breakdown: DriverBreakdown[] = [];
      if (operatingCost != null) {
        breakdown.push({
          label: "Estimert drift",
          movement: "Driftskostnader i perioden",
          amount_mnok: operatingCost,
          per_share_nok: operatingCost * scale,
        });
      }
      if (interestIncome != null && Math.abs(interestIncome) > 1e-9) {
        breakdown.push({
          label: "Renteinntekter",
          movement: "Rapportert renteinntekt, periodisert",
          amount_mnok: interestIncome,
          per_share_nok: interestIncome * scale,
        });
      }
      if (otherMovements != null) {
        breakdown.push({
          label: "Restpost",
          movement: interestIncome == null
            ? "Rest etter identifiserte kontantbevegelser"
            : "Rest etter identifiserte kontantbevegelser, drift og renter",
          amount_mnok: otherMovements,
          per_share_nok: otherMovements * scale,
        });
      }
      result.push({
        ...driver,
        breakdown: breakdown.length > 0 ? breakdown : undefined,
      });
      continue;
    }
    result.push(driver);
  }
  return result.sort((left, right) => right.per_share_nok - left.per_share_nok);
}

function driverHasChange(driver: DisplayDriver) {
  const effects = driver.breakdown ?? [driver];
  return effects.some((effect) => (
    Math.abs(effect.amount_mnok ?? 0) > 1e-9
    || Math.abs(effect.per_share_nok) > 1e-9
  ));
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
    const load = async () => {
      setLoading(true);
      try {
        const payload = await fetchPreloadedJson<Payload>(discountHistoryUrl(period));
        if (!active) return;
        if (payload.estimated) setCache((current) => ({ ...current, [period.key]: payload.estimated! }));
        setFailed(false);
      } catch (error) {
        if (!active) return;
        setFailed(true);
      } finally {
        if (active) setLoading(false);
      }
    };
    void load();
    return () => { active = false; };
  }, [period.key, period.days]);

  const current = data?.current;
  const change = data?.change;
  const components = sortCompositionByValue(
    compositionWithoutSeparateFxRow(current?.composition ?? []),
  );
  const displayedNavPerShare = current?.nav_per_share ?? (live?.ready ? live.nav_per_share : null);
  const displayedSharesOutstanding = current?.shares_outstanding ?? live?.shares_outstanding;
  const displayedDiscountPct = current?.discount_pct ?? live?.discount_pct;
  const changedDrivers = groupedDrivers(change?.drivers ?? []).filter(driverHasChange);

  return (
    <div className="investorPage navV2">
      <section className="estimatedHero card">
        <div>
          <span className="label">NAV</span>
          <h2>{displayedNavPerShare != null ? `${value(displayedNavPerShare)} kr per aksje` : "Laster …"}</h2>
          <p>Beregnet på {integer(displayedSharesOutstanding)} utestående aksjer.</p>
        </div>
        <div className="estimatedHeroSide">
          <div><span>Rabatt</span><strong>{value(displayedDiscountPct, 1)} %</strong></div>
          <small>Sist oppdatert {dateTimeLabel(live?.calculated_at)}</small>
          <small>Kontrolleres hvert 30. minutt</small>
        </div>
      </section>

      <section className="card compositionCard">
        <div className="cardHeader">
          <div><span className="label">SAMMENSETNING</span><h2>Hva består NAV av i dag?</h2></div>
          <span className="pill">{dateLabel(current?.date ?? live?.as_of_date)}</span>
        </div>
        {loading && !data && <p className="dataNotice">Beregner sammensetningen …</p>}
        {failed && !data && <p className="dataNotice">Kunne ikke hente NAV-sammensetningen.</p>}
        {data && !data.ready && <p className="dataNotice">Historisk NAV er ikke komplett nok ennå.</p>}
        {components.length > 0 && (
          <div className="compositionTable">
            <div className="compositionHead"><span>Komponent</span><span>Verdi</span><span>Per aksje</span><span>Beregning</span></div>
            {components.map((item) => {
              const available = item.key !== "life360" || displayAvailable(item.details);
              return (
                <div className="compositionRow" key={item.key}>
                  <strong>{item.key === "life360" ? "Life360" : item.label}</strong>
                  <span>{available ? `${value(item.amount_mnok, 1)} mill. kr` : "–"}</span>
                  <span className={available && item.per_share_nok < 0 ? "negative" : ""}>{available ? `${value(item.per_share_nok)} kr` : "–"}</span>
                  <small>{available ? item.formula : "Mangler gyldig LIF-kurs og rapportanker"}</small>
                </div>
              );
            })}
            <div className="compositionTotal">
              <strong>NAV</strong>
              <span>{value(current?.nav_total_mnok, 1)} mill. kr</span>
              <span>{value(current?.nav_per_share)} kr</span>
              <small>Sum av komponentene over</small>
            </div>
          </div>
        )}
      </section>

      <section className="card navDriversCard">
        <div className="cardHeader driverHeader">
          <div><span className="label">ENDRING</span><h2>Hva har flyttet NAV?</h2></div>
          <PeriodButtons selected={period} onChange={setPeriod} />
        </div>
        {change?.ready && (
          <p className="dataNotice">
            Valgt periode {period.label}: faktisk sammenligning {dateLabel(change.resolved_start)} → {dateLabel(change.current_date)}
            {change.requested_start && change.resolved_start && change.requested_start !== change.resolved_start
              ? ` (ønsket start ${dateLabel(change.requested_start)})`
              : ""}
          </p>
        )}
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
              {changedDrivers.map((driver) => {
                const available = driver.key !== "life360" || displayAvailable(driver.details);
                return (
                  <div className="compositionRow" key={driver.key}>
                    <div className="driverLabel"><strong>{driver.label}</strong>{driver.breakdown?.map((part) => <small key={part.label}>{part.label}</small>)}</div>
                    <div className="driverCell"><span>{driver.breakdown ? "Samlet effekt" : driverMovement(driver)}</span>{driver.breakdown?.map((part) => <small key={part.label}>{part.movement}</small>)}</div>
                    <div className="driverCell"><span className={available ? ((driver.amount_mnok ?? 0) >= 0 ? "positive" : "negative") : ""}>{available ? (driver.amount_mnok == null ? "–" : `${signed(driver.amount_mnok, 1)} mill. kr`) : "–"}</span>{driver.breakdown?.map((part) => <small className={(part.amount_mnok ?? 0) >= 0 ? "positive" : "negative"} key={part.label}>{part.amount_mnok == null ? "–" : `${signed(part.amount_mnok, 1)} mill. kr`}</small>)}</div>
                    <div className="driverCell"><span className={available ? (driver.per_share_nok >= 0 ? "positive" : "negative") : ""}>{available ? `${signed(driver.per_share_nok)} kr/aksje` : "–"}</span>{driver.breakdown?.map((part) => <small className={part.per_share_nok >= 0 ? "positive" : "negative"} key={part.label}>{signed(part.per_share_nok)} kr/aksje</small>)}</div>
                  </div>
                );
              })}
              <div className="compositionTotal">
                <strong>NAV</strong>
                <span>{dateLabel(change.resolved_start)} → {dateLabel(change.current_date)}</span>
                <span>–</span>
                <span className={(change.change_per_share_nok ?? 0) >= 0 ? "positive" : "negative"}>{signed(change.change_per_share_nok)} kr/aksje</span>
              </div>
            </div>
            <p className="methodNote">Bemobi deles i aksjekurs og BRL/NOK. Bekreftede Bemobi-utdelinger vises som én livsløpslinje: først som fordring fra ex-dato og deretter som utbetalt netto kontantbevegelse på betalingsdato. Overgangen fra fordring til kontanter endrer ikke NAV i seg selv. Øvrig kontantendring deles i estimert drift, kildebelagt rapportert renteinntekt og en resterende kontantendring. Renteinntekt fra halvårsrapportene periodiseres etter kalenderdager og Otellos rapporterte USD/NOK-perioder; det er en attribusjon, ikke en antakelse om eksakt daglig opptjening. Tilbakekjøp vises som to egne effekter: kontantbruk og færre utestående aksjer. NAV/aksje-effekten fordeles symmetrisk mellom verdiendring og aksjeantall, slik at kryssleddet ikke avhenger av rekkefølgen og summen fortsatt avstemmer mot nettoendringen i NAV.</p>
          </>
        ) : (
          <p className="dataNotice">Venter på nok historiske NAV-observasjoner for valgt periode.</p>
        )}
      </section>
    </div>
  );
}

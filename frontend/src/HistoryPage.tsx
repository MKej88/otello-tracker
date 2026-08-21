import { useEffect, useState } from "react";
import "./history-page.css";

type HistoryPoint = {
  date: string;
  nav_per_share: number | null;
  otec_price: number | null;
  discount_pct: number | null;
  status: string;
};

type DiscountStatistics = {
  count: number;
  current_discount_pct: number | null;
  average_discount_pct: number | null;
  median_discount_pct: number | null;
  p10_discount_pct: number | null;
  p25_discount_pct: number | null;
  p75_discount_pct: number | null;
  p90_discount_pct: number | null;
  minimum_discount_pct: number | null;
  minimum_discount_date: string | null;
  maximum_discount_pct: number | null;
  maximum_discount_date: string | null;
  current_percentile: number | null;
  premium_observation_count: number;
};

type CurrentReference = {
  ready?: boolean;
  reason?: string;
  as_of_date?: string | null;
  quality?: string | null;
  nav_per_share?: number | null;
  otec_price?: number | null;
  discount_pct?: number | null;
  conservative_nav_per_share?: number | null;
  conservative_discount_pct?: number | null;
  date?: string | null;
};

type DiscountHistory = {
  ready: boolean;
  data_status?: string;
  period_days?: number;
  from?: string | null;
  to?: string | null;
  raw_count?: number;
  point_count?: number;
  basis?: {
    type?: string;
    model_scope?: string | null;
    calculation_version?: string | null;
    note?: string | null;
  };
  statistics?: DiscountStatistics;
  current_validated?: CurrentReference | null;
  current_economic?: CurrentReference | null;
  points?: HistoryPoint[];
};

type Period = { label: string; days: number };

const PERIODS: Period[] = [
  { label: "30 D", days: 30 },
  { label: "1 ÅR", days: 365 },
  { label: "3 ÅR", days: 1095 },
  { label: "10 ÅR", days: 3650 }
];
const AUTO_REFRESH_MS = 5 * 60 * 1000;

function value(input: number | null | undefined, digits = 1) {
  if (input == null || !Number.isFinite(input)) return "–";
  return input.toLocaleString("nb-NO", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits
  });
}

function dateLabel(input?: string | null) {
  if (!input) return "–";
  const [year, month, day] = input.split("-");
  return year && month && day ? `${day}.${month}.${year}` : input;
}

function discountLabel(input?: number | null) {
  if (input == null || !Number.isFinite(input)) return "–";
  return input >= 0
    ? `${value(input, 1)} % rabatt`
    : `${value(Math.abs(input), 1)} % premie`;
}

function percentileText(percentile?: number | null) {
  if (percentile == null || !Number.isFinite(percentile)) return "For lite historikk til rangering.";
  if (percentile >= 80) {
    return `Dagens validerte rabatt er større enn omtrent ${value(percentile, 0)} % av observasjonene i valgt periode.`;
  }
  if (percentile <= 20) {
    return `Dagens validerte rabatt er lavere enn omtrent ${value(100 - percentile, 0)} % av observasjonene i valgt periode.`;
  }
  return `Dagens validerte rabatt ligger rundt ${value(percentile, 0)}. persentil i valgt periode.`;
}

function chartPolyline(points: HistoryPoint[], min: number, max: number) {
  const spread = max - min || 1;
  return points
    .map((point, index) => {
      const discount = point.discount_pct;
      if (discount == null || !Number.isFinite(discount)) return null;
      const x = points.length === 1 ? 50 : 3 + (index / (points.length - 1)) * 94;
      const y = 92 - ((discount - min) / spread) * 82;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .filter(Boolean)
    .join(" ");
}

function DiscountHistoryChart({ points, statistics }: { points: HistoryPoint[]; statistics: DiscountStatistics }) {
  const discounts = points
    .map((point) => point.discount_pct)
    .filter((item): item is number => item != null && Number.isFinite(item));
  if (discounts.length < 2) {
    return <div className="historyChartEmpty">Venter på nok historiske NAV-observasjoner</div>;
  }

  const references = [
    statistics.median_discount_pct,
    statistics.p25_discount_pct,
    statistics.p75_discount_pct,
    0
  ].filter((item): item is number => item != null && Number.isFinite(item));
  const min = Math.min(...discounts, ...references);
  const max = Math.max(...discounts, ...references);
  const spread = max - min || 1;
  const y = (input: number) => 92 - ((input - min) / spread) * 82;
  const medianY = statistics.median_discount_pct == null ? null : y(statistics.median_discount_pct);
  const p25Y = statistics.p25_discount_pct == null ? null : y(statistics.p25_discount_pct);
  const p75Y = statistics.p75_discount_pct == null ? null : y(statistics.p75_discount_pct);
  const zeroY = min <= 0 && max >= 0 ? y(0) : null;

  return (
    <div className="historyChart">
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-label="Historisk NAV-rabatt og persentiler">
        {[18, 38, 58, 78].map((gridY) => (
          <line className="historyGridLine" x1="0" x2="100" y1={gridY} y2={gridY} key={gridY} />
        ))}
        {p25Y != null && p75Y != null && (
          <rect className="historyInterquartile" x="3" y={Math.min(p25Y, p75Y)} width="94" height={Math.abs(p75Y - p25Y)} />
        )}
        {zeroY != null && <line className="historyZeroLine" x1="3" x2="97" y1={zeroY} y2={zeroY} />}
        {medianY != null && <line className="historyMedianLine" x1="3" x2="97" y1={medianY} y2={medianY} />}
        <polyline className="historyDiscountLine" points={chartPolyline(points, min, max)} />
      </svg>
      <div className="historyChartLegend">
        <span className="historyDiscountLegend">NAV-rabatt</span>
        <span className="historyMedianLegend">Median {discountLabel(statistics.median_discount_pct)}</span>
        <span className="historyBandLegend">P25–P75</span>
      </div>
      <div className="historyChartDates">
        <span>{dateLabel(points[0]?.date)}</span>
        <span>{dateLabel(points.at(-1)?.date)}</span>
      </div>
    </div>
  );
}

export default function HistoryPage() {
  const [period, setPeriod] = useState<Period>(PERIODS[1]);
  const [cache, setCache] = useState<Record<number, DiscountHistory>>({});
  const [failed, setFailed] = useState(false);
  const [loading, setLoading] = useState(false);
  const data = cache[period.days] ?? null;

  useEffect(() => {
    const controller = new AbortController();
    let active = true;

    const load = async () => {
      setLoading(true);
      try {
        const response = await fetch(
          `/api/dashboard/discount-history?days=${period.days}&max_points=600`,
          { signal: controller.signal }
        );
        if (!response.ok) throw new Error("Historikk API-feil");
        const result = await response.json() as DiscountHistory;
        if (!active) return;
        setCache((current) => ({ ...current, [period.days]: result }));
        setFailed(false);
      } catch (error) {
        if (!active || (error instanceof DOMException && error.name === "AbortError")) return;
        setFailed(true);
      } finally {
        if (active) setLoading(false);
      }
    };

    void load();
    const timer = window.setInterval(() => void load(), AUTO_REFRESH_MS);
    return () => {
      active = false;
      controller.abort();
      window.clearInterval(timer);
    };
  }, [period.days]);

  if (data == null && loading) {
    return <div className="historyNotice">Laster NAV-rabatthistorikk …</div>;
  }
  if (data == null && failed) {
    return <div className="historyNotice"><strong>Kunne ikke hente historikkdata.</strong></div>;
  }
  if (!data?.ready || !data.statistics) {
    return (
      <div className="historyNotice">
        <strong>Historisk NAV-rabatt er ikke klar.</strong>
        <span>Venter på validerte NAV-observasjoner.</span>
      </div>
    );
  }

  const statistics = data.statistics;
  const points = data.points ?? [];
  const economic = data.current_economic;
  const validated = data.current_validated;
  const scope = data.basis?.model_scope === "FULL" ? "FULL NAV" : "CORE NAV";
  const periodCoverage = `${dateLabel(data.from)}–${dateLabel(data.to)}`;
  const premiumShare = statistics.count > 0
    ? statistics.premium_observation_count / statistics.count * 100
    : null;
  const distributionRows = [
    ["10. persentil", discountLabel(statistics.p10_discount_pct)],
    ["25. persentil", discountLabel(statistics.p25_discount_pct)],
    ["Median", discountLabel(statistics.median_discount_pct)],
    ["75. persentil", discountLabel(statistics.p75_discount_pct)],
    ["90. persentil", discountLabel(statistics.p90_discount_pct)],
    ["Gjennomsnitt", discountLabel(statistics.average_discount_pct)]
  ];

  return (
    <div className="historyPage">
      <section className="card historyHero">
        <div>
          <span className="label">VERDSETTELSE / HISTORIKK</span>
          <h2>Hvor uvanlig er dagens NAV-rabatt?</h2>
          <p>
            Historisk rabatt/premie mellom OTEC-kursen og validert NAV, med persentiler og
            dagens investorjusterte økonomiske NAV vist separat.
          </p>
        </div>
        <div className="historyPeriodSelector" aria-label="Velg historikkperiode">
          {PERIODS.map((item) => (
            <button
              className={item.days === period.days ? "active" : ""}
              key={item.days}
              onClick={() => setPeriod(item)}
              type="button"
            >
              {item.label}
            </button>
          ))}
        </div>
      </section>

      {failed && data != null && (
        <div className="historyStaleWarning" role="status">
          Ny historikkoppdatering feilet. Viser sist vellykket hentede data for denne perioden.
        </div>
      )}

      <section className="historyKpiGrid">
        <article className="card historyKpi historyKpiPrimary">
          <span className="label">Økonomisk NAV i dag</span>
          <strong>{economic?.ready ? `${value(economic.nav_per_share, 2)} kr` : "–"}</strong>
          <small>{economic?.ready ? discountLabel(economic.discount_pct) : "Investor-NAV ikke klar"}</small>
        </article>
        <article className="card historyKpi">
          <span className="label">Validert rabatt i dag</span>
          <strong>{discountLabel(validated?.discount_pct)}</strong>
          <small>{scope} · {dateLabel(validated?.date)}</small>
        </article>
        <article className="card historyKpi">
          <span className="label">Historisk median</span>
          <strong>{discountLabel(statistics.median_discount_pct)}</strong>
          <small>{periodCoverage}</small>
        </article>
        <article className="card historyKpi">
          <span className="label">Dagens plassering</span>
          <strong>{statistics.current_percentile == null ? "–" : `${value(statistics.current_percentile, 0)}. persentil`}</strong>
          <small>Høyere = større NAV-rabatt</small>
        </article>
      </section>

      <section className="card historyMainChart">
        <div className="cardHeader historyChartHeader">
          <div>
            <span className="label">{scope}</span>
            <h2>Rabatt/premie over tid</h2>
          </div>
          <div className="historyCoverage">
            <span>{statistics.count.toLocaleString("nb-NO")} observasjoner</span>
            <span>{loading ? "Oppdaterer …" : periodCoverage}</span>
          </div>
        </div>
        <DiscountHistoryChart points={points} statistics={statistics} />
        <p className="historyInterpretation">{percentileText(statistics.current_percentile)}</p>
      </section>

      <section className="historyDetailGrid">
        <article className="card">
          <div className="cardHeader">
            <div><span className="label">Fordeling</span><h2>Historiske nivåer</h2></div>
          </div>
          <div className="historyRows">
            {distributionRows.map(([label, result]) => (
              <div key={label}><span>{label}</span><strong>{result}</strong></div>
            ))}
          </div>
        </article>

        <article className="card">
          <div className="cardHeader">
            <div><span className="label">Ytterpunkter</span><h2>Historisk spenn</h2></div>
          </div>
          <div className="historyRows">
            <div>
              <span>Største rabatt</span>
              <strong>{discountLabel(statistics.maximum_discount_pct)}</strong>
              <small>{dateLabel(statistics.maximum_discount_date)}</small>
            </div>
            <div>
              <span>Laveste rabatt / høyeste premie</span>
              <strong>{discountLabel(statistics.minimum_discount_pct)}</strong>
              <small>{dateLabel(statistics.minimum_discount_date)}</small>
            </div>
            <div>
              <span>Observasjoner med premie</span>
              <strong>{statistics.premium_observation_count.toLocaleString("nb-NO")}</strong>
              <small>{premiumShare == null ? "–" : `${value(premiumShare, 1)} % av observasjonene`}</small>
            </div>
          </div>
        </article>
      </section>

      <section className="card historyMethod">
        <div>
          <span className="label">Metode</span>
          <h2>To ulike NAV-begreper holdes adskilt</h2>
        </div>
        <p>{data.basis?.note}</p>
        <p>
          Persentilene er beskrivende historikk, ikke et kjøps- eller salgssignal. Serien bruker
          én siste komplett NAV-observasjon per dato før grafen eventuelt nedprøves for visning.
        </p>
      </section>
    </div>
  );
}

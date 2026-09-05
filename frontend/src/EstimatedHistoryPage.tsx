import { useEffect, useMemo, useState, type PointerEvent } from "react";
import { discountHistoryUrl, investorPeriods, type InvestorPeriod } from "./investorPeriods";
import { fetchPreloadedJson } from "./navigationDataPreload";
import ResourceNotice from "./ResourceNotice";
import { formatDate, formatNumber } from "./uiFormat";
import { usePollingResource } from "./usePollingResource";

type Point = { date: string; nav_per_share?: number | null; otec_price?: number | null; discount_pct?: number | null };
type Statistics = {
  count: number;
  current_discount_pct?: number | null;
  average_discount_pct?: number | null;
  median_discount_pct?: number | null;
  p10_discount_pct?: number | null;
  p90_discount_pct?: number | null;
  minimum_discount_pct?: number | null;
  minimum_discount_date?: string | null;
  maximum_discount_pct?: number | null;
  maximum_discount_date?: string | null;
  current_percentile?: number | null;
};
type EstimatedHistory = { ready: boolean; from?: string; to?: string; observation_count?: number; chart_point_count?: number; points?: Point[]; statistics?: Statistics; note?: string };
type Payload = { estimated?: EstimatedHistory };
type EconomicNav = { ready: boolean; discount_pct?: number | null; calculated_at?: string | null };
const AUTO_REFRESH_MS = 2 * 60 * 1000;

function finiteNumber(value?: number | null): value is number {
  return value != null && Number.isFinite(value);
}

function chartDate(input?: string | null) {
  if (!input) return "–";
  const [year, month, day] = input.slice(0, 10).split("-");
  if (!year || !month || !day) return input;
  return `${day}.${month}.${year}`;
}

function signedPp(value?: number | null) {
  if (!finiteNumber(value)) return "–";
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}${formatNumber(Math.abs(value), 1)} pp`;
}

function percentileContext(value?: number | null) {
  if (!finiteNumber(value)) return "Historisk plassering mangler";
  const clamped = Math.max(0, Math.min(100, value));
  return `Rabatten har bare vært større ${formatNumber(100 - clamped, 0)} % av tiden`;
}

function PeriodButtons({ selected, onChange }: { selected: InvestorPeriod; onChange: (period: InvestorPeriod) => void }) {
  return (
    <div className="periodButtons" aria-label="Velg historikkperiode">
      {investorPeriods().map((period) => (
        <button type="button" key={period.key} className={period.key === selected.key ? "active" : ""} onClick={() => onChange(period)}>{period.label}</button>
      ))}
    </div>
  );
}

function DiscountChart({ points, stats }: { points: Point[]; stats: Statistics }) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const usable = points.filter(
    (point) => finiteNumber(point.discount_pct),
  );
  if (usable.length < 2) return <div className="dataNotice">Venter på nok NAV-observasjoner til grafen.</div>;

  const values = usable.map((point) => Number(point.discount_pct));
  const referenceValues = [stats.p10_discount_pct, stats.median_discount_pct, stats.p90_discount_pct]
    .filter(finiteNumber);
  const scaleValues = [...values, ...referenceValues];
  const priceValues = usable
    .map((point) => point.otec_price)
    .filter(finiteNumber);
  let min = Math.min(...scaleValues);
  let max = Math.max(...scaleValues);
  const padding = Math.max(1, (max - min) * 0.12);
  min = Math.floor((min - padding) / 5) * 5;
  max = Math.ceil((max + padding) / 5) * 5;
  if (min === max) max = min + 5;

  const left = 78;
  const right = 910;
  const top = 20;
  const bottom = 285;
  const x = (index: number) => left + index / (usable.length - 1) * (right - left);
  const y = (result: number) => bottom - (result - min) / (max - min) * (bottom - top);
  const polyline = usable.map((point, index) => `${x(index).toFixed(1)},${y(Number(point.discount_pct)).toFixed(1)}`).join(" ");
  const priceMin = priceValues.length > 0 ? Math.floor(Math.min(...priceValues) / 5) * 5 : 0;
  let priceMax = priceValues.length > 0 ? Math.ceil(Math.max(...priceValues) / 5) * 5 : 5;
  if (priceMin === priceMax) priceMax = priceMin + 5;
  const priceY = (price: number) =>
    bottom - ((price - priceMin) / (priceMax - priceMin)) * (bottom - top);
  const pricePolyline = usable
    .map((point, index) =>
      finiteNumber(point.otec_price)
        ? `${x(index).toFixed(1)},${priceY(point.otec_price).toFixed(1)}`
        : null,
    )
    .filter((coordinate): coordinate is string => coordinate != null)
    .join(" ");
  const yTicks = Array.from({ length: 6 }, (_, index) => min + (max - min) * index / 5);
  const priceTicks = Array.from(
    { length: 6 },
    (_, index) => priceMin + ((priceMax - priceMin) * index) / 5,
  );
  const xTickIndexes = Array.from(new Set([0, Math.round((usable.length - 1) * 0.25), Math.round((usable.length - 1) * 0.5), Math.round((usable.length - 1) * 0.75), usable.length - 1]));
  const zeroInRange = min <= 0 && max >= 0;
  const hasPercentileBand = finiteNumber(stats.p10_discount_pct) && finiteNumber(stats.p90_discount_pct);
  const hovered = hoverIndex == null ? null : usable[hoverIndex];
  const hoverX = hoverIndex == null ? null : x(hoverIndex);
  const tooltipLeft = hoverX == null ? 50 : Math.max(12, Math.min(88, hoverX / 10));

  const handlePointerMove = (event: PointerEvent<SVGSVGElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    if (bounds.width <= 0) return;
    const viewX = ((event.clientX - bounds.left) / bounds.width) * 1000;
    const ratio = Math.max(0, Math.min(1, (viewX - left) / (right - left)));
    setHoverIndex(Math.round(ratio * (usable.length - 1)));
  };

  return (
    <div className="axisChart">
      <svg
        viewBox="0 0 1000 330"
        role="img"
        aria-label="Historisk rabatt til NAV"
        onPointerMove={handlePointerMove}
        onPointerLeave={() => setHoverIndex(null)}
      >
        {hasPercentileBand && (
          <rect
            className="historyPercentileBand"
            x={left}
            y={Math.min(y(stats.p10_discount_pct), y(stats.p90_discount_pct))}
            width={right - left}
            height={Math.abs(y(stats.p10_discount_pct) - y(stats.p90_discount_pct))}
          />
        )}
        {yTicks.map((tick) => {
          const py = y(tick);
          return <g key={tick}><line className="axisGrid" x1={left} x2={right} y1={py} y2={py} /><text className="axisLabel" x={left - 12} y={py + 5} textAnchor="end">{formatNumber(tick, 0)} %</text></g>;
        })}
        {zeroInRange && <line className="axisZero" x1={left} x2={right} y1={y(0)} y2={y(0)} />}
        {finiteNumber(stats.median_discount_pct) && (
          <line className="historyMedianLine" x1={left} x2={right} y1={y(stats.median_discount_pct)} y2={y(stats.median_discount_pct)} />
        )}
        <polyline className="estimatedDiscountLine" points={polyline} />
        {pricePolyline && <polyline className="estimatedPriceLine" points={pricePolyline} />}
        {priceTicks.map((tick) => {
          const py = priceY(tick);
          return <text key={tick} className="axisLabel axisPriceLabel" x={right + 12} y={py + 5}>{formatNumber(tick, 0)} kr</text>;
        })}
        {xTickIndexes.map((index) => {
          const px = x(index);
          return <g key={index}><line className="axisTick" x1={px} x2={px} y1={bottom} y2={bottom + 7} /><text className="axisLabel" x={px} y={bottom + 26} textAnchor="middle">{chartDate(usable[index]?.date)}</text></g>;
        })}
        {hovered && hoverX != null && (
          <g aria-hidden="true">
            <line className="historyHoverGuide" x1={hoverX} x2={hoverX} y1={top} y2={bottom} />
            <circle className="historyHoverPoint" cx={hoverX} cy={y(Number(hovered.discount_pct))} r="5" />
            {finiteNumber(hovered.otec_price) && (
              <circle className="historyHoverPricePoint" cx={hoverX} cy={priceY(hovered.otec_price)} r="4" />
            )}
          </g>
        )}
        <text className="axisTitle" transform="rotate(-90 18 150)" x="18" y="150" textAnchor="middle">Rabatt / premie</text>
        <text className="axisTitle axisPriceTitle" transform="rotate(90 982 150)" x="982" y="150" textAnchor="middle">OTEC-kurs</text>
        <text className="axisTitle" x={(left + right) / 2} y="326" textAnchor="middle">Dato</text>
      </svg>
      {hovered && (
        <div className="historyChartTooltip" style={{ left: `${tooltipLeft}%` }}>
          <strong>{formatDate(hovered.date)}</strong>
          <span><em>NAV</em><b>{formatNumber(hovered.nav_per_share, 2)} kr</b></span>
          <span><em>OTEC</em><b>{formatNumber(hovered.otec_price, 2)} kr</b></span>
          <span><em>Rabatt</em><b>{formatNumber(hovered.discount_pct, 1)} %</b></span>
        </div>
      )}
      <div className="axisChartLegend" aria-hidden="true">
        <span className="discountLegendItem">Rabatt / premie</span>
        <span className="priceLegendItem">OTEC-kurs</span>
        {hasPercentileBand && <span className="percentileBandLegendItem">10.–90. persentil</span>}
        {finiteNumber(stats.median_discount_pct) && <span className="medianLegendItem">Median</span>}
      </div>
      <p className="chartSummary">
        Fra {formatDate(usable[0]?.date)} til {formatDate(usable.at(-1)?.date)}.
        Siste historiske observasjon {formatDate(usable.at(-1)?.date)}: rabatt {formatNumber(usable.at(-1)?.discount_pct, 1)} % og
        OTEC-kurs {formatNumber(usable.at(-1)?.otec_price, 2)} kr.
      </p>
    </div>
  );
}

export default function EstimatedHistoryPage() {
  const periods = useMemo(() => investorPeriods(), []);
  const [period, setPeriod] = useState(periods[4]);
  const [cache, setCache] = useState<Record<string, EstimatedHistory>>({});
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const data = cache[period.key];
  const { data: economicNav } = usePollingResource<EconomicNav>(
    "/api/dashboard/economic",
    AUTO_REFRESH_MS,
    true,
  );

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

  const stats = data?.statistics;
  const points = data?.points ?? [];
  const currentDiscount = finiteNumber(economicNav?.discount_pct) ? economicNav.discount_pct : null;
  const medianDiscount = finiteNumber(stats?.median_discount_pct) ? stats.median_discount_pct : null;
  const discountSpread = currentDiscount != null && medianDiscount != null
    ? currentDiscount - medianDiscount
    : null;
  const discountSpreadText = discountSpread == null
    ? "Sammenligning mot median mangler"
    : discountSpread > 0.05
      ? "Bredere enn periodens median"
      : discountSpread < -0.05
        ? "Smalere enn periodens median"
        : "På linje med periodens median";

  return (
    <div className="investorPage historyV2">
      <section className="card historyV2Header">
        <div>
          <span className="label">HISTORIKK</span>
          <h2>Rabatt til NAV</h2>
          <p>Basert på historiske NAV-beregninger, markedsdata og valutakurser. Kun datoer med godt nok datagrunnlag brukes.</p>
        </div>
        <PeriodButtons selected={period} onChange={setPeriod} />
      </section>

      {failed && !data && <ResourceNotice kind="error">Kunne ikke hente NAV-historikk.</ResourceNotice>}
      {loading && !data && <ResourceNotice>Beregner NAV-historikk …</ResourceNotice>}
      {data && !data.ready && <ResourceNotice kind="empty">Det finnes foreløpig ikke nok kildebelagt historikk til denne perioden.</ResourceNotice>}

      {data?.ready && stats && (
        <>
          <section className="historyKpiGrid">
            <article className="card historyKpi"><span className="label">Dagens rabatt</span><strong>{formatNumber(currentDiscount)} %</strong><small>Live · {formatDate(economicNav?.calculated_at)}</small></article>
            <article className="card historyKpi"><span className="label">Median</span><strong>{formatNumber(stats.median_discount_pct)} %</strong><small>{(data.observation_count ?? stats.count).toLocaleString("nb-NO")} dagsobservasjoner</small></article>
            <article className="card historyKpi"><span className="label">Avvik fra median</span><strong>{signedPp(discountSpread)}</strong><small>{discountSpreadText}</small></article>
            <article className="card historyKpi"><span className="label">Dagens persentil</span><strong>{formatNumber(stats.current_percentile, 0)}. persentil</strong><small>{percentileContext(stats.current_percentile)}</small></article>
          </section>

          <section className="card historyAxisCard">
            <div className="cardHeader"><div><span className="label">NAV</span><h2>Rabatt / premie over tid</h2></div><span className="pill">{loading ? "OPPDATERER" : period.label}</span></div>
            <DiscountChart points={points} stats={stats} />
          </section>

          <section className="historyDetailGrid">
            <article className="card"><div className="cardHeader"><div><span className="label">Fordeling</span><h2>Historiske nivåer</h2></div></div><div className="placeholderRows"><div><span>10. persentil</span><strong>{formatNumber(stats.p10_discount_pct)} %</strong></div><div><span>Median</span><strong>{formatNumber(stats.median_discount_pct)} %</strong></div><div><span>90. persentil</span><strong>{formatNumber(stats.p90_discount_pct)} %</strong></div></div></article>
            <article className="card"><div className="cardHeader"><div><span className="label">Ytterpunkter</span><h2>Historisk spenn</h2></div></div><div className="placeholderRows historyRangeRows"><div><span>Største rabatt</span><strong>{formatNumber(stats.maximum_discount_pct)} %</strong><small>{formatDate(stats.maximum_discount_date)}</small></div><div><span>Laveste rabatt / høyeste premie</span><strong>{formatNumber(stats.minimum_discount_pct)} %</strong><small>{formatDate(stats.minimum_discount_date)}</small></div></div></article>
          </section>
          {data.note && <p className="methodNote">{data.note}</p>}
        </>
      )}
    </div>
  );
}
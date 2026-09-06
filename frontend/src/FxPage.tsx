import { useMemo, useState } from "react";

import { usePollingResource } from "./usePollingResource";
import "./fx-page.css";

const REFRESH_MS = 10 * 60 * 1000;
const MILLION = 1_000_000;

type RangeKey = "1M" | "3M" | "YTD" | "1Y" | "3Y" | "5Y";
type FxPoint = {
  date: string;
  brl_nok: number;
  usd_nok?: number | null;
  usd_brl?: number | null;
};
type PeriodSnapshot = {
  reference_date?: string | null;
  brl_nok_pct?: number | null;
  usd_nok_pct?: number | null;
  usd_brl_pct?: number | null;
};
type FxPayload = {
  ready: boolean;
  as_of_date?: string;
  current?: {
    brl_nok?: number | null;
    usd_nok?: number | null;
    usd_brl?: number | null;
  };
  periods?: Record<string, PeriodSnapshot>;
  range_1y?: {
    low?: number | null;
    high?: number | null;
    average?: number | null;
    percentile?: number | null;
  };
  series?: FxPoint[];
  sources?: Array<{ code: string; name: string; url?: string | null }>;
  method_note?: string;
};
type SummaryPayload = {
  ready?: boolean;
  as_of_date?: string | null;
  brl_nok?: number | null;
  bmob3_price?: number | null;
  bemobi_shares?: number | null;
  bemobi_value_mnok?: number | null;
  shares_outstanding?: number | null;
  brl_nok_insights?: {
    daily_pct?: number | null;
    month_pct?: number | null;
    nav_effect_1m_per_share_nok?: number | null;
    range_1y?: {
      low?: number | null;
      high?: number | null;
      position_pct?: number | null;
    };
  } | null;
  bemobi_insights?: {
    price_brl?: number | null;
    holding_shares?: number | null;
    ownership_pct?: number | null;
  } | null;
};
type EconomicPayload = {
  ready?: boolean;
  shares_outstanding?: number | null;
  nav_per_share?: number | null;
};

type LinePoint = { date: string; value: number };

const ranges: RangeKey[] = ["1M", "3M", "YTD", "1Y", "3Y", "5Y"];

function finite(value: number | null | undefined): value is number {
  return value != null && Number.isFinite(value);
}

function number(value: number | null | undefined, digits = 2) {
  if (!finite(value)) return "–";
  return value.toLocaleString("nb-NO", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function signedPct(value: number | null | undefined, digits = 1) {
  if (!finite(value)) return "–";
  return `${value > 0 ? "+" : ""}${number(value, digits)} %`;
}

function signedNok(value: number | null | undefined, digits = 2) {
  if (!finite(value)) return "–";
  return `${value > 0 ? "+" : ""}${number(value, digits)} kr`;
}

function dateLabel(value?: string | null) {
  if (!value) return "–";
  const [year, month, day] = value.slice(0, 10).split("-");
  return year && month && day ? `${day}.${month}.${year}` : value;
}

function cutoffDate(endDate: string, range: RangeKey) {
  const end = new Date(`${endDate}T12:00:00Z`);
  if (range === "YTD") return `${endDate.slice(0, 4)}-01-01`;
  const days = range === "1M" ? 31 : range === "3M" ? 93 : range === "1Y" ? 366 : range === "3Y" ? 1096 : 1830;
  end.setUTCDate(end.getUTCDate() - days);
  return end.toISOString().slice(0, 10);
}

function periodSeries(series: FxPoint[], range: RangeKey, endDate: string) {
  const cutoff = cutoffDate(endDate, range);
  const result = series.filter((point) => point.date >= cutoff && finite(point.brl_nok));
  return result.length >= 2 ? result : series.slice(-2);
}

function pctChange(current?: number | null, reference?: number | null) {
  if (!finite(current) || !finite(reference) || reference === 0) return null;
  return (current / reference - 1) * 100;
}

function movingAverage(series: FxPoint[], window: number): LinePoint[] {
  if (series.length < window) return [];
  const result: LinePoint[] = [];
  let sum = 0;
  for (let index = 0; index < series.length; index += 1) {
    sum += series[index].brl_nok;
    if (index >= window) sum -= series[index - window].brl_nok;
    if (index >= window - 1) {
      result.push({ date: series[index].date, value: sum / window });
    }
  }
  return result;
}

function latestAverage(series: LinePoint[]) {
  return series.length ? series[series.length - 1].value : null;
}

function rangeStats(points: FxPoint[]) {
  const values = points.map((point) => point.brl_nok).filter(finite);
  if (!values.length) return { low: null, high: null, average: null, percentile: null };
  const current = values[values.length - 1];
  const low = Math.min(...values);
  const high = Math.max(...values);
  const average = values.reduce((sum, value) => sum + value, 0) / values.length;
  const percentile = values.filter((value) => value <= current).length / values.length * 100;
  return { low, high, average, percentile };
}

function chartPath(
  points: LinePoint[],
  min: number,
  max: number,
  width: number,
  height: number,
  padX: number,
  padY: number,
) {
  if (points.length < 2) return "";
  const span = Math.max(max - min, 0.000001);
  return points.map((point, index) => {
    const x = padX + index / (points.length - 1) * (width - padX * 2);
    const y = padY + (max - point.value) / span * (height - padY * 2);
    return `${index === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`;
  }).join(" ");
}

function nearestLineByDate(series: LinePoint[], dates: string[]) {
  const lookup = new Map(series.map((point) => [point.date, point.value]));
  return dates.flatMap((date) => {
    const value = lookup.get(date);
    return finite(value) ? [{ date, value }] : [];
  });
}

function FxChart({ series, range }: { series: FxPoint[]; range: RangeKey }) {
  const endDate = series[series.length - 1]?.date;
  const filtered = useMemo(
    () => endDate ? periodSeries(series, range, endDate) : [],
    [series, range, endDate],
  );
  const ma50All = useMemo(() => movingAverage(series, 50), [series]);
  const ma200All = useMemo(() => movingAverage(series, 200), [series]);
  if (filtered.length < 2) return <div className="fxChartEmpty">Historikk mangler</div>;

  const dates = filtered.map((point) => point.date);
  const spotLine = filtered.map((point) => ({ date: point.date, value: point.brl_nok }));
  const ma50 = nearestLineByDate(ma50All, dates);
  const ma200 = nearestLineByDate(ma200All, dates);
  const allValues = [
    ...spotLine.map((point) => point.value),
    ...ma50.map((point) => point.value),
    ...ma200.map((point) => point.value),
  ];
  const minRaw = Math.min(...allValues);
  const maxRaw = Math.max(...allValues);
  const padding = Math.max((maxRaw - minRaw) * 0.12, 0.015);
  const min = minRaw - padding;
  const max = maxRaw + padding;
  const width = 1000;
  const height = 330;
  const padX = 62;
  const padY = 24;
  const grid = Array.from({ length: 5 }, (_, index) => max - index / 4 * (max - min));
  const labelIndices = [0, Math.round((filtered.length - 1) / 2), filtered.length - 1];

  return (
    <div className="fxChartWrap">
      <svg className="fxChart" role="img" viewBox={`0 0 ${width} ${height}`} aria-label={`BRL/NOK ${range}`}>
        {grid.map((value) => {
          const y = padY + (max - value) / (max - min) * (height - padY * 2);
          return (
            <g key={value}>
              <line className="fxGridLine" x1={padX} x2={width - padX} y1={y} y2={y} />
              <text className="fxAxisLabel" x={padX - 10} y={y + 4} textAnchor="end">{number(value, 2)}</text>
            </g>
          );
        })}
        <path className="fxLine fxLineSpot" d={chartPath(spotLine, min, max, width, height, padX, padY)} />
        {ma50.length > 1 ? <path className="fxLine fxLineMa50" d={chartPath(ma50, min, max, width, height, padX, padY)} /> : null}
        {ma200.length > 1 ? <path className="fxLine fxLineMa200" d={chartPath(ma200, min, max, width, height, padX, padY)} /> : null}
        {labelIndices.map((index) => {
          const point = filtered[index];
          const x = padX + index / (filtered.length - 1) * (width - padX * 2);
          return <text className="fxAxisLabel" key={`${point.date}-${index}`} x={x} y={height - 4} textAnchor={index === 0 ? "start" : index === filtered.length - 1 ? "end" : "middle"}>{dateLabel(point.date).slice(0, 5)}</text>;
        })}
      </svg>
      <div className="fxLegend" aria-hidden="true">
        <span><i className="spot" />BRL/NOK</span>
        <span><i className="ma50" />50 dager</span>
        <span><i className="ma200" />200 dager</span>
      </div>
    </div>
  );
}

function DriverRow({ label, value, explanation }: { label: string; value: number | null | undefined; explanation: string }) {
  const tone = finite(value) && value !== 0 ? (value > 0 ? "positive" : "negative") : "neutral";
  return (
    <div className="fxDriverRow">
      <div><strong>{label}</strong><span>{explanation}</span></div>
      <strong className={tone}>{signedPct(value)}</strong>
    </div>
  );
}

function periodDriverExplanation(snapshot?: PeriodSnapshot) {
  const usdNok = snapshot?.usd_nok_pct;
  const usdBrl = snapshot?.usd_brl_pct;
  const pieces: string[] = [];
  if (finite(usdNok)) pieces.push(usdNok > 0 ? "NOK har svekket seg mot USD" : usdNok < 0 ? "NOK har styrket seg mot USD" : "NOK er uendret mot USD");
  if (finite(usdBrl)) pieces.push(usdBrl < 0 ? "BRL har styrket seg mot USD" : usdBrl > 0 ? "BRL har svekket seg mot USD" : "BRL er uendret mot USD");
  return pieces.join(". ") || "Ikke nok data til å dekomponere perioden.";
}

export default function FxPage() {
  const { data: fx, refreshFailed: fxRefreshFailed } = usePollingResource<FxPayload>(
    "/api/fx/dashboard",
    REFRESH_MS,
    true,
  );
  const { data: summary, refreshFailed: summaryRefreshFailed } = usePollingResource<SummaryPayload>(
    "/api/dashboard/summary",
    REFRESH_MS,
    true,
  );
  const { data: economic } = usePollingResource<EconomicPayload>(
    "/api/dashboard/economic",
    REFRESH_MS,
    true,
  );
  const [range, setRange] = useState<RangeKey>("1Y");
  const [driverPeriod, setDriverPeriod] = useState<"m1" | "ytd">("m1");

  if (!fx && !fxRefreshFailed) {
    return <section className="card viewFallback"><span className="label">BRL/NOK</span><strong>Henter valutadata …</strong></section>;
  }
  if (!fx?.ready) {
    return (
      <section className="card fxError">
        <span className="label">BRL/NOK</span>
        <strong>Kunne ikke bygge valutasiden</strong>
        <p>BRL/NOK-historikken er ikke tilgjengelig i datagrunnlaget ennå.</p>
      </section>
    );
  }

  const series = fx.series ?? [];
  const spot = fx.current?.brl_nok ?? summary?.brl_nok;
  const bmob3 = summary?.bemobi_insights?.price_brl ?? summary?.bmob3_price;
  const holdingShares = summary?.bemobi_insights?.holding_shares ?? summary?.bemobi_shares;
  const ownershipPct = summary?.bemobi_insights?.ownership_pct;
  const sharesOutstanding = summary?.shares_outstanding ?? economic?.shares_outstanding;
  const bemobiValueM = summary?.bemobi_value_mnok
    ?? (finite(bmob3) && finite(holdingShares) && finite(spot) ? bmob3 * holdingShares * spot / MILLION : null);
  const onePctM = finite(bemobiValueM) ? bemobiValueM * 0.01 : null;
  const onePctPerShare = finite(onePctM) && finite(sharesOutstanding) && sharesOutstanding > 0
    ? onePctM * MILLION / sharesOutstanding
    : null;
  const m1 = fx.periods?.m1?.brl_nok_pct ?? summary?.brl_nok_insights?.month_pct;
  const ytd = fx.periods?.ytd?.brl_nok_pct;
  const y1 = fx.periods?.y1?.brl_nok_pct;
  const navEffect1m = summary?.brl_nok_insights?.nav_effect_1m_per_share_nok;

  const ma50 = latestAverage(movingAverage(series, 50));
  const ma200 = latestAverage(movingAverage(series, 200));
  const selectedSeries = series.length && fx.as_of_date ? periodSeries(series, range, fx.as_of_date) : [];
  const selectedStats = rangeStats(selectedSeries);
  const selectedMove = selectedSeries.length >= 2
    ? pctChange(selectedSeries[selectedSeries.length - 1].brl_nok, selectedSeries[0].brl_nok)
    : null;

  const ytdReference = fx.periods?.ytd?.reference_date
    ? series.find((point) => point.date === fx.periods?.ytd?.reference_date)
    : null;
  const isolatedYtdFxM = finite(bmob3) && finite(holdingShares) && finite(spot) && finite(ytdReference?.brl_nok)
    ? bmob3 * holdingShares * (spot - ytdReference.brl_nok) / MILLION
    : null;
  const isolatedYtdFxPerShare = finite(isolatedYtdFxM) && finite(sharesOutstanding) && sharesOutstanding > 0
    ? isolatedYtdFxM * MILLION / sharesOutstanding
    : null;

  const sensitivityMoves = [-10, -5, -1, 0, 1, 5, 10];
  const sensitivity = sensitivityMoves.map((move) => {
    const scenarioFx = finite(spot) ? spot * (1 + move / 100) : null;
    const valueM = finite(scenarioFx) && finite(bmob3) && finite(holdingShares)
      ? scenarioFx * bmob3 * holdingShares / MILLION
      : null;
    const deltaM = finite(valueM) && finite(bemobiValueM) ? valueM - bemobiValueM : null;
    const deltaPerShare = finite(deltaM) && finite(sharesOutstanding) && sharesOutstanding > 0
      ? deltaM * MILLION / sharesOutstanding
      : null;
    return { move, scenarioFx, valueM, deltaM, deltaPerShare };
  });

  const activeDriver = fx.periods?.[driverPeriod];
  const activeDriverLabel = driverPeriod === "m1" ? "siste måned" : "hittil i år";
  const refreshWarning = fxRefreshFailed || summaryRefreshFailed;

  return (
    <div className="investorPage fxPage">
      <section className="fxHero">
        <div>
          <span className="eyebrow">VALUTA · OTELLO NAV</span>
          <h2>BRL/NOK som verdidriver</h2>
          <p>Isoler valutaeffekten på Otellos Bemobi-post, se hvor dagens kurs ligger historisk og skill mellom bevegelser i BRL og NOK.</p>
        </div>
        <div className="fxHeroMeta">
          <span>Sist oppdatert</span>
          <strong>{dateLabel(fx.as_of_date)}</strong>
          {refreshWarning ? <small>Oppfrisking feilet – viser siste lagrede data</small> : null}
        </div>
      </section>

      <section className="fxKpiGrid">
        <article className="card fxKpi primary"><span className="label">BRL/NOK NÅ</span><strong>{number(spot, 4)}</strong><small>{signedPct(fx.periods?.d1?.brl_nok_pct)} siste dag</small></article>
        <article className="card fxKpi"><span className="label">1 MÅNED</span><strong className={finite(m1) && m1 >= 0 ? "positive" : "negative"}>{signedPct(m1)}</strong><small>BRL mot NOK</small></article>
        <article className="card fxKpi"><span className="label">YTD</span><strong className={finite(ytd) && ytd >= 0 ? "positive" : "negative"}>{signedPct(ytd)}</strong><small>BRL mot NOK</small></article>
        <article className="card fxKpi"><span className="label">1 ÅR</span><strong className={finite(y1) && y1 >= 0 ? "positive" : "negative"}>{signedPct(y1)}</strong><small>BRL mot NOK</small></article>
        <article className="card fxKpi accent"><span className="label">FX → NAV · 1M</span><strong>{signedNok(navEffect1m)}</strong><small>Symmetrisk FX-attribusjon per OTEC-aksje</small></article>
        <article className="card fxKpi"><span className="label">1 % STERKERE BRL</span><strong>{finite(onePctM) ? `${number(onePctM, 1)} MNOK` : "–"}</strong><small>{finite(onePctPerShare) ? `${number(onePctPerShare * 100, 1)} øre per OTEC-aksje` : "Direkte Bemobi-effekt"}</small></article>
      </section>

      <section className="card fxHistoryCard">
        <div className="fxSectionHead">
          <div><span className="label">HISTORIKK</span><h3>BRL/NOK</h3></div>
          <div className="periodButtons fxRangeButtons" role="group" aria-label="Velg periode">
            {ranges.map((item) => <button className={range === item ? "active" : ""} key={item} onClick={() => setRange(item)} type="button">{item}</button>)}
          </div>
        </div>
        <div className="fxHistorySummary">
          <div><span>Endring {range}</span><strong>{signedPct(selectedMove)}</strong></div>
          <div><span>Lav</span><strong>{number(selectedStats.low, 4)}</strong></div>
          <div><span>Snitt</span><strong>{number(selectedStats.average, 4)}</strong></div>
          <div><span>Høy</span><strong>{number(selectedStats.high, 4)}</strong></div>
          <div><span>Persentil</span><strong>{finite(selectedStats.percentile) ? `${number(selectedStats.percentile, 0)}.` : "–"}</strong></div>
        </div>
        <FxChart range={range} series={series} />
      </section>

      <section className="fxTwoColumn">
        <article className="card fxDriverCard">
          <div className="fxSectionHead compact">
            <div><span className="label">HVA DRIVER KRYSSKURSEN?</span><h3>BRL eller NOK?</h3></div>
            <div className="periodButtons fxDriverButtons">
              <button className={driverPeriod === "m1" ? "active" : ""} onClick={() => setDriverPeriod("m1")} type="button">1M</button>
              <button className={driverPeriod === "ytd" ? "active" : ""} onClick={() => setDriverPeriod("ytd")} type="button">YTD</button>
            </div>
          </div>
          <p className="fxFormula">BRL/NOK = USD/NOK ÷ USD/BRL</p>
          <DriverRow label="BRL/NOK" value={activeDriver?.brl_nok_pct} explanation={`Samlet endring ${activeDriverLabel}`} />
          <DriverRow label="USD/NOK" value={activeDriver?.usd_nok_pct} explanation="Positiv endring betyr svakere NOK mot USD" />
          <DriverRow label="USD/BRL" value={activeDriver?.usd_brl_pct} explanation="Negativ endring betyr sterkere BRL mot USD" />
          <p className="fxDriverConclusion">{periodDriverExplanation(activeDriver)}</p>
        </article>

        <article className="card fxPositionCard">
          <span className="label">DAGENS NIVÅ</span>
          <h3>Historisk posisjon</h3>
          <div className="fxPositionGauge">
            <div className="fxPositionTrack"><span style={{ width: `${Math.max(0, Math.min(100, fx.range_1y?.percentile ?? 0))}%` }} /></div>
            <div><span>{number(fx.range_1y?.low, 4)}</span><strong>{finite(fx.range_1y?.percentile) ? `${number(fx.range_1y?.percentile, 0)}. persentil` : "–"}</strong><span>{number(fx.range_1y?.high, 4)}</span></div>
          </div>
          <div className="fxPositionRows">
            <div><span>1-årssnitt</span><strong>{number(fx.range_1y?.average, 4)}</strong></div>
            <div><span>50 dagers snitt</span><strong>{number(ma50, 4)}</strong></div>
            <div><span>200 dagers snitt</span><strong>{number(ma200, 4)}</strong></div>
            <div><span>Spot vs. 200d</span><strong>{signedPct(pctChange(spot, ma200))}</strong></div>
          </div>
        </article>
      </section>

      <section className="card fxExposureCard">
        <div className="fxSectionHead">
          <div><span className="label">OTELLOS BRL-EKSPONERING</span><h3>Direkte effekt gjennom Bemobi-posten</h3></div>
          <div className="fxExposureHeadline"><span>Bemobi-post</span><strong>{finite(bemobiValueM) ? `${number(bemobiValueM, 0)} MNOK` : "–"}</strong></div>
        </div>
        <div className="fxExposureMeta">
          <span>{finite(holdingShares) ? `${number(holdingShares / MILLION, 2)}m Bemobi-aksjer` : "Bemobi-beholdning mangler"}</span>
          <span>{finite(ownershipPct) ? `${number(ownershipPct, 2)} % eierskap` : ""}</span>
          <span>{finite(bmob3) ? `BMOB3 ${number(bmob3, 2)} BRL` : ""}</span>
        </div>
        <div className="fxTableWrap">
          <table className="fxTable">
            <thead><tr><th>BRL-bevegelse</th><th>BRL/NOK</th><th>Bemobi-post</th><th>Endring</th><th>Direkte / OTEC</th></tr></thead>
            <tbody>
              {sensitivity.map((row) => (
                <tr className={row.move === 0 ? "current" : ""} key={row.move}>
                  <td>{row.move === 0 ? "Dagens kurs" : signedPct(row.move, 0)}</td>
                  <td>{number(row.scenarioFx, 4)}</td>
                  <td>{finite(row.valueM) ? `${number(row.valueM, 0)} MNOK` : "–"}</td>
                  <td className={finite(row.deltaM) && row.deltaM > 0 ? "positive" : finite(row.deltaM) && row.deltaM < 0 ? "negative" : ""}>{finite(row.deltaM) ? `${row.deltaM > 0 ? "+" : ""}${number(row.deltaM, 1)} MNOK` : "–"}</td>
                  <td className={finite(row.deltaPerShare) && row.deltaPerShare > 0 ? "positive" : finite(row.deltaPerShare) && row.deltaPerShare < 0 ? "negative" : ""}>{signedNok(row.deltaPerShare)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="fxFootnote">BMOB3-kurs og Bemobi-beholdning holdes konstant. Tabellen viser den direkte verdien av Bemobi-posten, ikke full NAV etter opsjonseffekt og øvrige eiendeler. Bruk <a href="#nav-sensitivitet">NAV-sensitivitet</a> for komplett BMOB3 × BRL/NOK-scenario.</p>
      </section>

      <section className="fxTwoColumn fxContextGrid">
        <article className="card fxContextCard">
          <span className="label">VALUTABIDRAG YTD</span>
          <h3>{signedNok(isolatedYtdFxPerShare)}</h3>
          <p>{finite(isolatedYtdFxM) ? `${isolatedYtdFxM > 0 ? "+" : ""}${number(isolatedYtdFxM, 1)} MNOK på Bemobi-posten` : "Ikke nok historikk til å beregne YTD-effekten."}</p>
          <small>Isolert beregning med dagens BMOB3-kurs og beholdning. Dette er ikke symmetrisk NAV-attribusjon.</small>
        </article>
        <article className="card fxContextCard">
          <span className="label">BEMOBI · OPERASJONELL FX</span>
          <h3>2Q26: 15 % → 20 %</h3>
          <p>Organisk omsetningsvekst var 15 % rapportert og 20 % på valutajustert basis. Valuta var dermed en motvind på om lag 5 prosentpoeng i kvartalet.</p>
          <small>Senest dokumentert i Bemobi 2Q26 / Otello 1H26. Denne effekten er separat fra NOK-omregningen av Otellos Bemobi-post.</small>
        </article>
      </section>

      <section className="card fxMethodCard">
        <div><span className="label">METODE OG KILDER</span><p>{fx.method_note}</p></div>
        <div className="fxSources">
          {(fx.sources ?? []).map((source) => source.url ? <a href={source.url} key={source.code} rel="noreferrer" target="_blank">{source.name}</a> : <span key={source.code}>{source.name}</span>)}
          <a href="#brasil">Brasil-makro →</a>
        </div>
      </section>
    </div>
  );
}

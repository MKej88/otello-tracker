import { useEffect, useState, type ReactNode } from "react";
import { usePollingResource } from "./usePollingResource";
import { formatDateTime, formatNumber } from "./uiFormat";
import { displayedChange, displayedOtecEffect, displayedTheoreticalOtecPrice, displayedFxMovement, displayedFxEffect, fxStatusLabel, displayedCombinedTheoreticalPrice, movementChart, statusLabel, waitingForOsloClose, type BemobiAfterOslo } from "./bemobiAfterOsloModel";
import "./bemobi-after-oslo.css";

function timeLabel(at?: string) {
  if (!at || !Number.isFinite(Date.parse(at))) return "—";
  return new Date(at).toLocaleTimeString("nb-NO", {
    timeZone: "Europe/Oslo", hour: "2-digit", minute: "2-digit",
  });
}


type MarketMovementProps = {
  title: string;
  change: number | null;
  tone: string;
  status: string;
  referenceLabel: string;
  referenceValue: string;
  latestLabel: string;
  latestValue: string;
  chart: ReturnType<typeof movementChart>;
  chartLabel: string;
  sourceNote: ReactNode;
};

/** Shared price/percentage/chart rows keep Bemobi and BRL/NOK aligned. */
function MarketMovement({
  title, change, tone, status, referenceLabel, referenceValue,
  latestLabel, latestValue, chart, chartLabel, sourceNote,
}: MarketMovementProps) {
  return (
    <div className="bemobiAfterOsloMarket">
      <header className="bemobiAfterOsloMarketHeader">
        <span className="label">ETTER CLOSE PÅ OSLO BØRS</span>
        <h2>{title}</h2>
      </header>
      <div className="bemobiAfterOsloMarketChange">
        <strong className={["bemobiAfterOsloValue", "numeric", tone].join(" ")}>
          {change == null ? "—" : (change > 0 ? "+" : "") + formatNumber(change, 2) + " %"}
        </strong>
        <div className="bemobiAfterOsloStatus" role="status">{status}</div>
      </div>
      <div className="bemobiAfterOsloPrices">
        <span>{referenceLabel}<strong className="numeric">{referenceValue}</strong></span>
        <span>{latestLabel}<strong className="numeric">{latestValue}</strong></span>
      </div>
      <div className="bemobiAfterOsloMarketChartPanel">
        {chart ? (
          <>
            <svg viewBox="0 0 480 100" preserveAspectRatio="none"
              className={["bemobiAfterOsloChart", tone].join(" ")}
              role="img" aria-label={chartLabel}>
              <line x1="8" x2="472" y1={chart.zeroY} y2={chart.zeroY} className="bemobiAfterOsloZero" />
              <polyline points={chart.line} />
            </svg>
            <div className="bemobiAfterOsloTimes numeric">
              <span>{timeLabel(chart.start)}</span><span>{timeLabel(chart.end)}</span>
            </div>
          </>
        ) : <><div className="bemobiAfterOsloChartPlaceholder">Kurshistorikk ikke tilgjengelig ennå</div><div className="bemobiAfterOsloTimes numeric"><span>—</span><span>—</span></div></>}
      </div>
      <div className="bemobiAfterOsloMarketSource">{sourceNote}</div>
    </div>
  );
}

export default function BemobiAfterOsloCard() {
  const { data, refreshFailed } = usePollingResource<BemobiAfterOslo>(
    "/api/market/bemobi-after-oslo", 2 * 60 * 1000,
  );
  // A stale response may remain cached until the next two-minute poll.
  // Re-render exactly at Oslo opening and hide every previous-session value.
  const [, setOpenBoundaryTick] = useState(0);
  useEffect(() => {
    const nextOpenMs = Date.parse(data?.next_oslo_open_at ?? "");
    const remaining = nextOpenMs - Date.now();
    if (!Number.isFinite(remaining) || remaining <= 0) return;
    const timer = window.setTimeout(() => setOpenBoundaryTick(value => value + 1), remaining);
    return () => window.clearTimeout(timer);
  }, [data?.next_oslo_open_at]);
  const waiting = waitingForOsloClose(data);
  const visibleData: BemobiAfterOslo | null = waiting && data
    ? { ...data, ready: false, status: "waiting_oslo_close",
        reference: undefined, latest: undefined, otec_effect: undefined,
        fx_movement: { ready: false, reason: "waiting_oslo_close" }, points: [] }
    : data;
  const displayRefreshFailed = refreshFailed && !waiting;
  const change = displayedChange(visibleData, displayRefreshFailed);
  const tone = change == null || change === 0 ? "neutral" : change > 0 ? "positive" : "negative";
  const chart = change == null ? null : movementChart(visibleData?.points);
  const reference = visibleData?.reference;
  const latest = visibleData?.latest;
  const effect = displayedOtecEffect(visibleData, displayRefreshFailed);
  const theoreticalPrice = displayedTheoreticalOtecPrice(visibleData, displayRefreshFailed);
  const fx = displayedFxMovement(visibleData, displayRefreshFailed);
  const rawFx = visibleData?.fx_movement;
  const fxEffect = displayedFxEffect(visibleData, displayRefreshFailed);
  const fxReference = rawFx?.reference_rate != null && Number.isFinite(rawFx.reference_rate) ? rawFx.reference_rate : null;
  const fxLatest = rawFx?.latest_rate != null && Number.isFinite(rawFx.latest_rate) ? rawFx.latest_rate : null;
  const fxChart = fx ? movementChart(fx.points) : null;
  const combinedPrice = displayedCombinedTheoreticalPrice(visibleData, displayRefreshFailed);
  const effectTone = effect?.change_per_share_nok == null || effect.change_per_share_nok === 0 ? "neutral" : effect.change_per_share_nok > 0 ? "positive" : "negative";
  const combinedTone = fxEffect?.combined_per_share_nok == null || fxEffect.combined_per_share_nok === 0 ? "neutral" : fxEffect.combined_per_share_nok > 0 ? "positive" : "negative";
  const fxTone = fx?.change_pct == null || fx.change_pct === 0 ? "neutral" : fx.change_pct > 0 ? "positive" : "negative";
  const fxEffectTone = fxEffect?.effect_per_share_nok == null || fxEffect.effect_per_share_nok === 0 ? "neutral" : fxEffect.effect_per_share_nok > 0 ? "positive" : "negative";
  const signed = (value: number, suffix: string) => `${value > 0 ? "+" : ""}${formatNumber(value, 2)}${suffix}`;
  const missingLabels: Record<string, string> = {
    otec_close: "OTEC-kurs ved close på Oslo Børs", fixed_fx: "fast valutakurs",
    bemobi_holding: "Bemobi-beholdning", otec_shares: "antall OTEC-aksjer",
    invalid_calculation: "gyldig beregningsgrunnlag",
  };
  return (
    <div className="bemobiAfterOsloGrid">
      <section className="card cardStandard bemobiAfterOslo bemobiAfterOsloMarketCard" aria-label="Bemobi siden Oslo Børs stengte">
        <MarketMovement
          title="Bemobi siden Oslo Børs stengte"
          change={change}
          tone={tone}
          status={statusLabel(visibleData?.status, displayRefreshFailed)}
          referenceLabel="Ved Oslo-slutt"
          referenceValue={reference ? "R$ " + formatNumber(reference.price, 2) : "—"}
          latestLabel="Siste kurs"
          latestValue={latest ? "R$ " + formatNumber(latest.price, 2) : "—"}
          chart={chart}
          chartLabel={change == null ? "Ingen Bemobi-kursutvikling tilgjengelig" : "Bemobis lagrede kursutvikling siden Oslo-slutt: " + formatNumber(change, 2) + " prosent."}
          sourceNote={<>
            {latest && <small>Siste kurstid: {formatDateTime(latest.observed_at)} · {latest.source === "YAHOO_FINANCE" ? "Yahoo Finance" : latest.source}{latest.delay_minutes === 15 ? " · 15 min forsinket" : ""}</small>}
            {!waiting && visibleData?.next_oslo_open_at && <small className="bemobiAfterOsloPeriod">Måles til Oslo-åpning: {formatDateTime(visibleData.next_oslo_open_at)}</small>}
          </>}
        />
        <details className="bemobiAfterOsloDetails">
          <summary>Vis kursgrunnlag</summary>
          <div>
            {visibleData?.oslo_close_at && <p>Oslo Børs stengte: {formatDateTime(visibleData.oslo_close_at)}.</p>}
            {reference && <p>Referansekurs: R$ {formatNumber(reference.price, 2)} · {formatDateTime(reference.observed_at)} · {reference.source === "YAHOO_FINANCE" ? "Yahoo Finance" : reference.source}.</p>}
            <p>{reference?.source === "YAHOO_FINANCE"
              ? "Omtrentlig referanse fra Yahoo Finance: sluttkursen i siste avsluttede minutt før close på Oslo Børs, høyst tre minutter tidligere."
              : "Omtrentlig referanse: B3s svartidspunkt minus 15 minutter. Godtas innen tre minutter fra close på Oslo Børs."} Alle tidspunkt vises i norsk tid.</p>
            <p>Bemobi-endringen gjelder aksjekursen i BRL. Valutaendringen vises separat og måles mot en lagret BRL/NOK-kurs nær Oslo-slutt. Begge målingene avsluttes ved neste børsåpning kl. 09:00 (etter handelskalenderen). Siste faktisk registrerte kurstid oppgis, også hvis den er tidligere enn kl. 09:00.</p>
          </div>
        </details>
      </section>
      <section className="card cardStandard bemobiAfterOslo otecEffect" aria-label="Teoretisk OTEC-effekt fra Bemobi">
        <span className="label">OTEC-EFFEKT</span>
        <h2>Bemobi og valuta per OTEC-aksje</h2>
        <strong className={`bemobiAfterOsloValue numeric ${combinedTone}`}>
          {fxEffect?.combined_pct_otec != null ? signed(fxEffect.combined_pct_otec, " %") : "—"}
        </strong>
        <div className={`otecEffectAmount numeric ${combinedTone}`}>
          {fxEffect?.combined_per_share_nok != null ? signed(fxEffect.combined_per_share_nok, " kr per OTEC-aksje") : waiting ? "—" : "Valutaeffekt ikke tilgjengelig"}
        </div>
        <div className="otecEffectBreakdown">
          <div><span>Bemobi-effekt</span><strong className={`numeric ${effectTone}`}>{effect ? signed(effect.change_per_share_nok!, " kr") : "—"}</strong></div>
          <div><span>Valutaeffekt</span><strong className={`numeric ${fxEffectTone}`}>{fxEffect?.effect_per_share_nok != null ? signed(fxEffect.effect_per_share_nok, " kr") : "—"}</strong></div>
          <div className="otecEffectTotal"><span>Samlet effekt</span><strong className={`numeric ${combinedTone}`}>{fxEffect?.combined_per_share_nok != null ? signed(fxEffect.combined_per_share_nok, " kr") : "—"}</strong></div>
        </div>
        <div className="otecTheoreticalPrice">
          <span>Teoretisk OTEC-kurs inkl. valuta</span>
          <strong className="numeric">{combinedPrice == null ? "—" : `${formatNumber(combinedPrice, 2)} kr`}</strong>
        </div>
        {theoreticalPrice != null && <small>Kun Bemobi, med valutakurs holdt fast: {formatNumber(theoreticalPrice, 2)} kr.</small>}
        <div className="bemobiAfterOsloStatus" role="status">
          {effect ? fxEffect ? "Beregnet fra Bemobi og BRL/NOK etter Oslo-slutt" : "Beregnet Bemobi-effekt; valutareferanse mangler"
            : change == null ? statusLabel(visibleData?.status, displayRefreshFailed)
            : `Mangler ${visibleData?.otec_effect?.missing?.map(key => missingLabels[key] ?? key).join(", ") || "beregningsgrunnlag"}`}
        </div>
        <small>Teoretisk estimat for Bemobi-investeringen fra Oslo-slutt til neste åpning; ikke en kursprognose.</small>
        <details className="bemobiAfterOsloDetails">
          <summary>Vis beregningsgrunnlag</summary>
          {effect && <>
            <p><b>OTEC ved Oslo-slutt:</b> {formatNumber(effect.otec_price_nok, 2)} kr · {effect.otec_source}{effect.otec_price_type === "LAST" ? " (omtrentlig)" : ""}.</p>
            <p><b>BRL/NOK:</b> {formatNumber(effect.fixed_brl_nok, 4)} ({formatDateTime(effect.fx_observed_at)}){fxEffect && <> → {formatNumber(fxEffect.latest_rate, 4)} ({formatDateTime(fxEffect.latest_at)})</>} · {effect.fx_source}{fxEffect && effect.fx_source !== fxEffect.latest_source ? ` / ${fxEffect.latest_source}` : ""}{fxEffect ? " · " : ""}{fxEffect && signed(fxEffect.change_pct!, " %")}.</p>
            <p><b>Aksjer:</b> {formatNumber(effect.holding_shares, 0)} Bemobi / {formatNumber(effect.otec_outstanding_shares, 0)} OTEC.</p>
          </>}
          <p><b>Metode:</b> Endring i (Bemobi-kurs × BRL/NOK) × Bemobi-beholdning / OTEC-aksjer. Teoretisk OTEC-kurs = Oslo-sluttkurs + beregnet effekt.</p>
          <p><b>Forbehold:</b> Kursgrunnlaget nær Oslo-slutt er omtrentlig. Øvrige NAV-endringer er ikke medregnet.</p>
        </details>
      </section>
      <section className="card cardStandard bemobiAfterOslo bemobiAfterOsloMarketCard bemobiAfterOsloFxCard" aria-label="BRL/NOK over perioden da Oslo Børs var stengt">
        <MarketMovement
          title="BRL/NOK siden Oslo Børs stengte"
          change={fx?.change_pct ?? null}
          tone={fxTone}
          status={fxStatusLabel(rawFx, displayRefreshFailed)}
          referenceLabel="Ved Oslo-slutt"
          referenceValue={fxReference != null ? formatNumber(fxReference, 4) + " NOK" : "—"}
          latestLabel="Siste kurs"
          latestValue={fxLatest != null ? formatNumber(fxLatest, 4) + " NOK" : "—"}
          chart={fxChart}
          chartLabel={fx ? "BRL/NOK i måleperioden: " + formatNumber(fx.change_pct!, 2) + " prosent endring." : "Ingen valutakursutvikling tilgjengelig"}
          sourceNote={fx
            ? <small>Kursgrunnlag: {formatDateTime(fx.reference_at)} → {formatDateTime(fx.latest_at)}.</small>
            : <small>{fxStatusLabel(rawFx, displayRefreshFailed)}. {fxLatest != null && rawFx?.latest_at
              ? `Siste dokumenterte kurs: ${formatDateTime(rawFx.latest_at)}. `
              : ""}Ingen prosentvis valutaeffekt beregnes uten gyldig referanse.</small>}
        />
        <details className="bemobiAfterOsloDetails">
          <summary>Vis kursgrunnlag</summary>
          <div>
            {fxReference != null && <p>BRL/NOK ved Oslo-slutt: {formatNumber(fxReference, 4)} NOK · {formatDateTime(rawFx?.reference_at)} · {rawFx?.reference_source || "Ukjent kilde"}.</p>}
            {fxLatest != null && <p>Siste dokumenterte valutakurs: {formatNumber(fxLatest, 4)} NOK · {formatDateTime(rawFx?.latest_at)} · {rawFx?.latest_source || "Ukjent kilde"}.</p>}
            {!fx && rawFx?.reason && <p>Årsakskode: <code>{rawFx.reason}</code>{rawFx.capture_reason ? <> · Kilde: <code>{rawFx.capture_reason}</code></> : null}{rawFx.capture_observed_at ? ` · Kildetid: ${formatDateTime(rawFx.capture_observed_at)}` : ""}.</p>}
            <p>Referansen ved Oslo-slutt er omtrentlig. Valutaendringen måles frem til neste Oslo-åpning og beregnes separat fra Bemobis aksjekurs.</p>
          </div>
        </details>
      </section>
    </div>
  );
}

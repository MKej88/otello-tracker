import { usePollingResource } from "./usePollingResource";
import { formatDateTime, formatNumber } from "./uiFormat";
import { displayedChange, displayedOtecEffect, displayedTheoreticalOtecPrice, movementChart, statusLabel, type BemobiAfterOslo } from "./bemobiAfterOsloModel";
import "./bemobi-after-oslo.css";

function timeLabel(at?: string) {
  if (!at || !Number.isFinite(Date.parse(at))) return "—";
  return new Date(at).toLocaleTimeString("nb-NO", {
    timeZone: "Europe/Oslo", hour: "2-digit", minute: "2-digit",
  });
}

export default function BemobiAfterOsloCard() {
  const { data, refreshFailed } = usePollingResource<BemobiAfterOslo>(
    "/api/market/bemobi-after-oslo", 2 * 60 * 1000,
  );
  const change = displayedChange(data, refreshFailed);
  const tone = change == null || change === 0 ? "neutral" : change > 0 ? "positive" : "negative";
  const chart = change == null ? null : movementChart(data?.points);
  const reference = data?.reference;
  const latest = data?.latest;
  const effect = displayedOtecEffect(data, refreshFailed);
  const theoreticalPrice = displayedTheoreticalOtecPrice(data, refreshFailed);
  const effectTone = effect?.change_pct == null || effect.change_pct === 0 ? "neutral" : effect.change_pct > 0 ? "positive" : "negative";
  const signed = (value: number, suffix: string) => `${value > 0 ? "+" : ""}${formatNumber(value, 2)}${suffix}`;
  const missingLabels: Record<string, string> = {
    otec_close: "OTEC-kurs ved close på Oslo Børs", fixed_fx: "fast valutakurs",
    bemobi_holding: "Bemobi-beholdning", otec_shares: "antall OTEC-aksjer",
    invalid_calculation: "gyldig beregningsgrunnlag",
  };
  return (
    <div className="bemobiAfterOsloGrid">
      <section className="card cardStandard bemobiAfterOslo" aria-label="Bemobi siden Oslo Børs stengte">
        <div className="bemobiAfterOsloMain">
          <div>
            <span className="label">ETTER CLOSE PÅ OSLO BØRS</span>
            <h2>Bemobi siden Oslo Børs stengte</h2>
            <strong className={`bemobiAfterOsloValue numeric ${tone}`}>
              {change == null ? "—" : `${change > 0 ? "+" : ""}${formatNumber(change, 2)} %`}
            </strong>
            <div className="bemobiAfterOsloStatus" role="status">
              {statusLabel(data?.status, refreshFailed)}
            </div>
            {data?.oslo_close_at && <small>close på Oslo Børs: {formatDateTime(data.oslo_close_at)}</small>}
          </div>
          <div className="bemobiAfterOsloMovement">
            <div className="bemobiAfterOsloPrices">
              <span>Ved close på Oslo Børs <strong className="numeric">{reference ? `R$ ${formatNumber(reference.price, 2)}` : "—"}</strong></span>
              <span>Siste kurs <strong className="numeric">{latest ? `R$ ${formatNumber(latest.price, 2)}` : "—"}</strong></span>
            </div>
            {chart && <>
              <svg viewBox="0 0 480 100" preserveAspectRatio="none" className={`bemobiAfterOsloChart ${tone}`} role="img"
                aria-label={`Bemobis lagrede kursutvikling siden close på Oslo Børs: ${formatNumber(change, 2)} prosent.`}>
                <line x1="8" x2="472" y1={chart.zeroY} y2={chart.zeroY} className="bemobiAfterOsloZero" />
                <polyline points={chart.line} />
              </svg>
              <div className="bemobiAfterOsloTimes numeric"><span>{timeLabel(chart.start)}</span><span>{timeLabel(chart.end)}</span></div>
            </>}
            {latest && <small>Siste kurstid: {formatDateTime(latest.observed_at)} · {latest.source === "YAHOO_FINANCE" ? "Yahoo Finance" : latest.source}{latest.delay_minutes === 15 ? " · 15 min forsinket" : ""}</small>}
          </div>
        </div>
        <details className="bemobiAfterOsloDetails">
          <summary>Vis kursgrunnlag</summary>
          <div>
            {reference && <p>Referansekurs: R$ {formatNumber(reference.price, 2)} · {formatDateTime(reference.observed_at)} · {reference.source === "YAHOO_FINANCE" ? "Yahoo Finance" : reference.source}.</p>}
            <p>{reference?.source === "YAHOO_FINANCE"
              ? "Omtrentlig referanse fra Yahoo Finance: sluttkursen i siste avsluttede minutt før close på Oslo Børs, høyst tre minutter tidligere."
              : "Omtrentlig referanse: B3s svartidspunkt minus 15 minutter. Godtas innen tre minutter fra close på Oslo Børs."} Alle tidspunkt vises i norsk tid.</p>
            <p>Endringen gjelder Bemobi-kursen i BRL. Den inkluderer ikke valutaeffekt og er ikke en prognose for Otello-kursen.</p>
          </div>
        </details>
      </section>
      <section className="card cardStandard bemobiAfterOslo otecEffect" aria-label="Teoretisk OTEC-effekt fra Bemobi">
        <span className="label">OTEC-EFFEKT</span>
        <h2>Bemobis bidrag per OTEC-aksje</h2>
        <strong className={`bemobiAfterOsloValue numeric ${effectTone}`}>
          {effect ? signed(effect.change_pct!, " %") : "—"}
        </strong>
        <div className={`otecEffectAmount numeric ${effectTone}`}>
          {effect ? signed(effect.change_per_share_nok!, " kr per OTEC-aksje") : "—"}
        </div>
        <div className="otecTheoreticalPrice">
          <span>Teoretisk OTEC-kurs</span>
          <strong className="numeric">{theoreticalPrice == null ? "—" : `${formatNumber(theoreticalPrice, 2)} kr`}</strong>
        </div>
        <div className="bemobiAfterOsloStatus" role="status">
          {effect ? "Beregnet fra Bemobi etter close på Oslo Børs"
            : change == null ? statusLabel(data?.status, refreshFailed)
            : `Mangler ${data?.otec_effect?.missing?.map(key => missingLabels[key] ?? key).join(", ") || "beregningsgrunnlag"}`}
        </div>
        <small>OTEC-kurs ved Oslo-slutt justert for Bemobi-bevegelsen. Valutakurs holdt fast.</small>
        <details className="bemobiAfterOsloDetails">
          <summary>Vis beregningsgrunnlag</summary>
          {effect && <>
            <p>OTEC ved close på Oslo Børs: {formatNumber(effect.otec_price_nok, 2)} kr · {effect.otec_source}
              {effect.otec_price_type === "LAST" ? " · siste tilgjengelige handel før close på Oslo Børs (omtrentlig)" : " · sluttkurs"}.</p>
            <p>Fast BRL/NOK: {formatNumber(effect.fixed_brl_nok, 4)} · {formatDateTime(effect.fx_observed_at)} · {effect.fx_source}.</p>
            <p>Bemobi-beholdning: {formatNumber(effect.holding_shares, 0)} aksjer. Utestående OTEC-aksjer: {formatNumber(effect.otec_outstanding_shares, 0)}.</p>
          </>}
          <p>Bemobis kursendring i BRL × Otellos Bemobi-aksjer × fast BRL/NOK ÷ utestående OTEC-aksjer gir kroner per aksje. Beløpet deles på OTEC-kursen ved samme close på Oslo Børs for å beregne prosenten.</p>
          <p>Teoretisk OTEC-kurs er OTEC-kursen ved Oslo-slutt pluss Bemobi-effekten per aksje. Beregningen bruker uavrundede verdier.</p>
          <p>Valutakurs og aksjegrunnlag fra referansedatoen holdes fast. Dette er et teoretisk verdiutslag, ikke en prognose for OTEC-kursen.</p>
        </details>
      </section>
    </div>
  );
}

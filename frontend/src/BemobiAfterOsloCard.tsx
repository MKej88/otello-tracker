import { usePollingResource } from "./usePollingResource";
import { formatDateTime, formatNumber } from "./uiFormat";
import { displayedChange, displayedOtecEffect, displayedTheoreticalOtecPrice, displayedFxMovement, displayedCombinedTheoreticalPrice, movementChart, statusLabel, type BemobiAfterOslo } from "./bemobiAfterOsloModel";
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
  const fx = displayedFxMovement(data, refreshFailed);
  const combinedPrice = displayedCombinedTheoreticalPrice(data, refreshFailed);
  const effectTone = effect?.change_pct == null || effect.change_pct === 0 ? "neutral" : effect.change_pct > 0 ? "positive" : "negative";
  const combinedTone = fx?.combined_pct_otec == null || fx.combined_pct_otec === 0 ? "neutral" : fx.combined_pct_otec > 0 ? "positive" : "negative";
  const fxTone = fx?.change_pct == null || fx.change_pct === 0 ? "neutral" : fx.change_pct > 0 ? "positive" : "negative";
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
        <div className="bemobiAfterOsloFxMovement">
          <div className="bemobiAfterOsloFxHeading">
            <b>BRL/NOK siden Oslo Børs stengte</b>
            <strong className={`numeric ${fxTone}`}>{fx?.change_pct != null ? signed(fx.change_pct, " %") : "—"}</strong>
          </div>
          {fx ? (
            <>
              <div className="bemobiAfterOsloPrices">
                <span>Ved Oslo-slutt <strong className="numeric">{formatNumber(fx.reference_rate, 4)} NOK</strong></span>
                <span>Siste kurs <strong className="numeric">{formatNumber(fx.latest_rate, 4)} NOK</strong></span>
              </div>
              <small>Referanse: {formatDateTime(fx.reference_at)} · siste kurs: {formatDateTime(fx.latest_at)}. Omtrentlig kurs ved Oslo-slutt.</small>
            </>
          ) : <small>Mangler valutakurs nær Oslo-stenging eller en senere oppdatert valutakurs. Ingen valutaeffekt beregnes.</small>}
        </div>
        <details className="bemobiAfterOsloDetails">
          <summary>Vis kursgrunnlag</summary>
          <div>
            {reference && <p>Referansekurs: R$ {formatNumber(reference.price, 2)} · {formatDateTime(reference.observed_at)} · {reference.source === "YAHOO_FINANCE" ? "Yahoo Finance" : reference.source}.</p>}
            <p>{reference?.source === "YAHOO_FINANCE"
              ? "Omtrentlig referanse fra Yahoo Finance: sluttkursen i siste avsluttede minutt før close på Oslo Børs, høyst tre minutter tidligere."
              : "Omtrentlig referanse: B3s svartidspunkt minus 15 minutter. Godtas innen tre minutter fra close på Oslo Børs."} Alle tidspunkt vises i norsk tid.</p>
            <p>Bemobi-endringen gjelder aksjekursen i BRL. Valutaendringen vises separat og måles mot en lagret BRL/NOK-kurs nær Oslo-slutt.</p>
          </div>
        </details>
      </section>
      <section className="card cardStandard bemobiAfterOslo otecEffect" aria-label="Teoretisk OTEC-effekt fra Bemobi">
        <span className="label">OTEC-EFFEKT</span>
        <h2>Bemobi og valuta per OTEC-aksje</h2>
        <strong className={`bemobiAfterOsloValue numeric ${combinedTone}`}>
          {fx?.combined_pct_otec != null ? signed(fx.combined_pct_otec, " %") : "—"}
        </strong>
        <div className={`otecEffectAmount numeric ${combinedTone}`}>
          {fx?.combined_per_share_nok != null ? signed(fx.combined_per_share_nok, " kr per OTEC-aksje") : "Valutaeffekt ikke tilgjengelig"}
        </div>
        <div className="otecEffectBreakdown">
          <div><span>Bemobi-effekt</span><strong className={`numeric ${effectTone}`}>{effect ? signed(effect.change_per_share_nok!, " kr") : "—"}</strong></div>
          <div><span>Valutaeffekt</span><strong className="numeric">{fx?.effect_per_share_nok != null ? signed(fx.effect_per_share_nok, " kr") : "—"}</strong></div>
          <div className="otecEffectTotal"><span>Samlet effekt</span><strong className={`numeric ${combinedTone}`}>{fx?.combined_per_share_nok != null ? signed(fx.combined_per_share_nok, " kr") : "—"}</strong></div>
        </div>
        <div className="otecTheoreticalPrice">
          <span>Teoretisk OTEC-kurs inkl. valuta</span>
          <strong className="numeric">{combinedPrice == null ? "—" : `${formatNumber(combinedPrice, 2)} kr`}</strong>
        </div>
        {theoreticalPrice != null && <small>Kun Bemobi, med valutakurs holdt fast: {formatNumber(theoreticalPrice, 2)} kr.</small>}
        <div className="bemobiAfterOsloStatus" role="status">
          {effect ? fx ? "Beregnet fra Bemobi og BRL/NOK etter Oslo-slutt" : "Beregnet Bemobi-effekt; valutareferanse mangler"
            : change == null ? statusLabel(data?.status, refreshFailed)
            : `Mangler ${data?.otec_effect?.missing?.map(key => missingLabels[key] ?? key).join(", ") || "beregningsgrunnlag"}`}
        </div>
        <small>Teoretisk kurs med utgangspunkt i OTEC ved Oslo-slutt. Aksje- og valutaeffekt vises separat.</small>
        <details className="bemobiAfterOsloDetails">
          <summary>Vis beregningsgrunnlag</summary>
          {effect && <>
            <p>OTEC ved close på Oslo Børs: {formatNumber(effect.otec_price_nok, 2)} kr · {effect.otec_source}
              {effect.otec_price_type === "LAST" ? " · siste tilgjengelige handel i børsøkten, inkludert sluttauksjonen (omtrentlig)" : " · sluttkurs"}.</p>
            <p>BRL/NOK ved Oslo-slutt: {formatNumber(effect.fixed_brl_nok, 4)} · {formatDateTime(effect.fx_observed_at)} · {effect.fx_source}{fx ? " (omtrentlig tidsnær referanse)" : " (eldre dagsreferanse for Bemobi-beregningen)" }.</p>
            {fx && <p>Siste BRL/NOK: {formatNumber(fx.latest_rate, 4)} · {formatDateTime(fx.latest_at)} · {fx.latest_source}. Valutaendring: {signed(fx.change_pct!, " %")}.</p>}
            <p>Bemobi-beholdning: {formatNumber(effect.holding_shares, 0)} aksjer. Utestående OTEC-aksjer: {formatNumber(effect.otec_outstanding_shares, 0)}.</p>
          </>}
          <p>Bemobi-effekt = (siste Bemobi-kurs − Bemobi ved Oslo-slutt) × BRL/NOK ved Oslo-slutt × Bemobi-aksjer / OTEC-aksjer.</p>
          <p>Valutaeffekt = siste Bemobi-kurs × (siste BRL/NOK − BRL/NOK ved Oslo-slutt) × Bemobi-aksjer / OTEC-aksjer. Samlet effekt er summen, uten dobbelttelling.</p>
          <p>Teoretisk OTEC-kurs er OTEC ved Oslo-slutt pluss samlet effekt per aksje. Uavrundede verdier brukes. Manglende tidsnær valutareferanse gir ingen beregnet samlet effekt.</p>
          <p>Alle estimatene gjelder kun Bemobi-investeringen. Øvrige endringer i Otellos NAV er ikke medregnet. Dette er ikke en prognose for faktisk OTEC-kurs.</p>
        </details>
      </section>
    </div>
  );
}

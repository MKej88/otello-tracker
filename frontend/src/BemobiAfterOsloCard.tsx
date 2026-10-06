import { usePollingResource } from "./usePollingResource";
import { formatDateTime, formatNumber } from "./uiFormat";
import { displayedChange, movementChart, statusLabel, type BemobiAfterOslo } from "./bemobiAfterOsloModel";
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
  return (
    <section className="card cardStandard bemobiAfterOslo" aria-label="Bemobi siden Oslo stengte">
      <div className="bemobiAfterOsloMain">
        <div>
          <span className="label">ETTER OSLO-SLUTT</span>
          <h2>Bemobi siden Oslo stengte</h2>
          <strong className={`bemobiAfterOsloValue numeric ${tone}`}>
            {change == null ? "—" : `${change > 0 ? "+" : ""}${formatNumber(change, 2)} %`}
          </strong>
          <div className="bemobiAfterOsloStatus" role="status">
            {statusLabel(data?.status, refreshFailed)}
          </div>
          {data?.oslo_close_at && <small>Oslo-slutt: {formatDateTime(data.oslo_close_at)}</small>}
        </div>
        <div className="bemobiAfterOsloMovement">
          <div className="bemobiAfterOsloPrices">
            <span>Ved Oslo-slutt <strong className="numeric">{reference ? `R$ ${formatNumber(reference.price, 2)}` : "—"}</strong></span>
            <span>Siste kurs <strong className="numeric">{latest ? `R$ ${formatNumber(latest.price, 2)}` : "—"}</strong></span>
          </div>
          {chart && <>
            <svg viewBox="0 0 480 100" preserveAspectRatio="none" className={`bemobiAfterOsloChart ${tone}`} role="img"
              aria-label={`Bemobis lagrede kursutvikling siden Oslo-slutt: ${formatNumber(change, 2)} prosent.`}>
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
          {reference && <p>Referansekurs: R$ {formatNumber(reference.price, 2)} · {formatDateTime(reference.observed_at)} · {reference.source}.</p>}
          <p>Omtrentlig referanse: B3s svartidspunkt minus 15 minutter. Godtas innen tre minutter fra Oslo-slutt. Alle tidspunkt vises i norsk tid.</p>
          <p>Endringen gjelder Bemobi-kursen i BRL. Den inkluderer ikke valutaeffekt og er ikke en prognose for Otello-kursen.</p>
        </div>
      </details>
    </section>
  );
}

import { useEffect, useMemo, useState } from "react";
import ResourceNotice from "./ResourceNotice";
import "./buyback-page.css";

type Program = {
  external_id?: string;
  start_date?: string | null;
  end_date?: string | null;
  max_shares?: number | null;
  cumulative_shares?: number | null;
  remaining_shares?: number | null;
  max_price_nok?: number | null;
  progress_pct?: number | null;
};

type LatestWeek = {
  period_start?: string | null;
  trade_date?: string | null;
  shares?: number | null;
  avg_price_nok?: string | number | null;
  amount_nok?: string | number | null;
  cumulative_program_shares?: number | null;
  cumulative_program_amount_nok?: string | number | null;
  treasury_shares_after?: number | null;
  market_volume_shares?: number | null;
  volume_share_pct?: number | null;
  safe_harbour_capacity_shares?: number | null;
  safe_harbour_utilization_pct?: number | null;
};

type Shares = {
  total_shares?: number | null;
  treasury_shares?: number | null;
  outstanding_shares?: number | null;
  effective_from?: string | null;
  treasury_source?: string | null;
};

type ForecastWeek = {
  from?: string;
  to?: string;
  expected_trading_days?: number;
};

type Forecast = {
  ready?: boolean;
  status?: string;
  forecast_week?: ForecastWeek;
  volume_model?: {
    adv20_shares?: number | null;
    safe_harbour_share?: number | null;
    week_start_capacity_estimate_shares?: number | null;
    volume_through?: string | null;
  };
  price_model?: {
    latest_close_nok?: number | null;
    program_cap_nok?: number | null;
    headroom_pct?: number | null;
    state?: string | null;
  };
  estimate?: {
    base_case_shares?: number | null;
    low_shares?: number | null;
    high_shares?: number | null;
    utilization_factor?: number | null;
    confidence?: string | null;
    warning?: string | null;
  };
};

type BacktestWeek = {
  period_start: string;
  period_end: string;
  actual_shares: number;
  walk_forward_prediction_shares: number;
  market_volume_shares?: number | null;
  actual_volume_share_pct?: number | null;
  safe_harbour_utilization_pct?: number | null;
  forecast_error_shares?: number | null;
  forecast_error_pct?: number | null;
};

type Dashboard = {
  ready: boolean;
  status?: string;
  as_of_date?: string;
  program?: Program;
  latest_week?: LatestWeek | null;
  shares?: Shares | null;
  forecast?: Forecast;
  backtest?: {
    metrics?: {
      weeks?: number;
      median_ape_pct?: number | null;
      wmape_pct?: number | null;
      within_10_pct?: number | null;
      within_20_pct?: number | null;
    };
    weeks?: BacktestWeek[];
  };
  completion?: {
    pace_shares_per_week?: number | null;
    basis?: string;
    estimated_weeks_remaining?: number | null;
    estimated_completion_date?: string | null;
    program_end_date?: string | null;
    extends_beyond_program_end?: boolean;
    price_cap_blocked?: boolean;
  };
  methodology_note?: string;
  nav_effect?: {
    per_share_nok?: number | null;
    pct?: number | null;
  };
};

const AUTO_REFRESH_MS = 2 * 60 * 1000;
const integer = new Intl.NumberFormat("nb-NO", { maximumFractionDigits: 0 });

function value(input: number | string | null | undefined, digits = 1) {
  if (input == null || input === "") return "–";
  const numeric = Number(input);
  if (!Number.isFinite(numeric)) return "–";
  return numeric.toLocaleString("nb-NO", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits
  });
}

function count(input: number | null | undefined) {
  return input == null || !Number.isFinite(input) ? "–" : integer.format(input);
}

function dateLabel(input?: string | null) {
  if (!input) return "–";
  const [year, month, day] = input.split("-");
  return year && month && day ? `${day}.${month}.${year}` : input;
}

function statusLabel(input?: string | null) {
  const labels: Record<string, string> = {
    HIGH: "HØY",
    MEDIUM: "MIDDELS",
    LOW: "LAV",
    OK: "AKTIVT",
    PRICE_CAP_BLOCKED: "MAKS KJØPSPRIS",
    OPEN: "ÅPEN",
    TIGHT: "NÆR MAKS KJØPSPRIS",
    ABOVE_CAP: "OVER MAKS KJØPSPRIS",
    UNKNOWN: "UKJENT"
  };
  return input ? labels[input.toUpperCase()] ?? input : "–";
}

function warningLabel(input?: string | null) {
  if (!input) return null;
  if (input.includes("above the program price cap")) {
    return "Siste sluttkurs er over programmets maksimale kjøpspris. Kjøp krever at kursen kommer under grensen eller at mandatet endres.";
  }
  if (input.includes("within 3% of the program price cap")) {
    return "Kursen er mindre enn 3 % under programmets maksimale kjøpspris. Gjennomføringen kan bli begrenset.";
  }
  return input;
}

function completionText(data?: Dashboard["completion"]) {
  if (!data?.estimated_weeks_remaining) return "Ikke beregnbart";
  const weeks = `${data.estimated_weeks_remaining} ${data.estimated_weeks_remaining === 1 ? "uke" : "uker"}`;
  return data.estimated_completion_date
    ? `ca. ${weeks} · ${dateLabel(data.estimated_completion_date)}`
    : `ca. ${weeks}`;
}

function sourceLabel(input?: string | null) {
  return input === "LATEST_BUYBACK" ? "Siste buyback-melding" : "Rapportert aksjetall";
}

function percentage(input: number | null | undefined, digits = 1) {
  return input == null || !Number.isFinite(input) ? "–" : `${value(input, digits)} %`;
}

export default function BuybackPage() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    const load = () => {
      fetch("/api/buybacks/dashboard")
        .then((response) => {
          if (!response.ok) throw new Error("Buyback dashboard API-feil");
          return response.json() as Promise<Dashboard>;
        })
        .then((result) => {
          if (!active) return;
          setData(result);
          setFailed(false);
        })
        .catch(() => {
          if (!active) return;
          setFailed(true);
        });
    };
    load();
    const timer = window.setInterval(load, AUTO_REFRESH_MS);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  const program = data?.program;
  const latest = data?.latest_week;
  const shares = data?.shares;
  const forecast = data?.forecast;
  const estimate = forecast?.estimate;
  const volume = forecast?.volume_model;
  const price = forecast?.price_model;
  const metrics = data?.backtest?.metrics;
  const weeks = useMemo(() => [...(data?.backtest?.weeks ?? [])].reverse(), [data]);
  const progress = Math.max(0, Math.min(100, program?.progress_pct ?? 0));
  const completionWarning = data?.completion?.extends_beyond_program_end;
  const forecastWarning = warningLabel(estimate?.warning);
  const headroom = price?.headroom_pct ?? (
    price?.program_cap_nok != null && price.latest_close_nok != null && price.latest_close_nok > 0
      ? (price.program_cap_nok / price.latest_close_nok - 1) * 100
      : null
  );
  const rangeSpan = (estimate?.high_shares ?? 0) - (estimate?.low_shares ?? 0);
  const basePosition = rangeSpan > 0
    ? Math.max(0, Math.min(100, ((estimate?.base_case_shares ?? 0) - (estimate?.low_shares ?? 0)) / rangeSpan * 100))
    : 50;

  if (data == null && !failed) {
    return <ResourceNotice>Laster tilbakekjøpsdata …</ResourceNotice>;
  }

  if (failed && data == null) {
    return (
      <ResourceNotice kind="error">
        <strong>Kunne ikke hente tilbakekjøpsdata.</strong>
        <span>Investoroversikten er midlertidig utilgjengelig.</span>
      </ResourceNotice>
    );
  }

  if (!data?.ready) {
    return (
      <div className="buybackNotice">
        <strong>Tilbakekjøpssiden mangler et aktivt datagrunnlag.</strong>
        <span>Status: {statusLabel(data?.status)}</span>
      </div>
    );
  }

  return (
    <div className="buybackPage">
      <section className="buybackHero card">
        <div className="buybackHeroCopy">
          <span className="label">Aktivt tilbakekjøpsprogram</span>
          <div className="buybackHeroTitle">
            <h2>{count(program?.cumulative_shares)} aksjer kjøpt</h2>
            <span className={`buybackStatus ${data.status === "OK" ? "ok" : "warn"}`}>
              {statusLabel(data.status)}
            </span>
          </div>
          <p>
            {count(program?.remaining_shares)} aksjer gjenstår av en maksimal ramme på {count(program?.max_shares)}.
            Basert på nåværende tempo er estimert ferdigstillelse {completionText(data.completion).toLowerCase()}.
          </p>
          <div className="buybackProgressTrack" aria-label={`Programmet er ${value(progress, 1)} prosent fullført`}>
            <span style={{ width: `${progress}%` }} />
          </div>
          <div className="buybackProgressLabels">
            <strong>{value(progress, 1)} % fullført</strong>
            <span>Start {dateLabel(program?.start_date)}{program?.end_date ? ` · mandat til ${dateLabel(program.end_date)}` : ""}</span>
          </div>
        </div>
        <div className="buybackHeroMetric">
          <span>Estimert ferdig</span>
          <strong>{data.completion?.estimated_weeks_remaining ?? "–"}</strong>
          <small>uker igjen</small>
          <em>{dateLabel(data.completion?.estimated_completion_date)}</em>
        </div>
      </section>

      {(completionWarning || forecastWarning || failed) && (
        <div className="buybackAlerts">
          {completionWarning && (
            <div className="buybackAlert">
              <strong>Estimert tempo rekker utover dagens programperiode.</strong>
              <span>Dette betyr ikke at programmet automatisk forlenges; mandatet må vurderes mot kommende børsmeldinger.</span>
            </div>
          )}
          {forecastWarning && (
            <div className="buybackAlert">
              <strong>Kursbegrensning</strong><span>{forecastWarning}</span>
            </div>
          )}
          {failed && (
            <div className="buybackAlert neutralAlert">
              <strong>Ny oppdatering feilet.</strong><span>Viser sist vellykket hentede data.</span>
            </div>
          )}
        </div>
      )}

      <section className="buybackKpis">
        <article className="card buybackKpi navEffectKpi">
          <span className="label">Netto NAV-økning fra programmet</span>
          <strong>{data.nav_effect?.per_share_nok == null ? "–" : `${value(data.nav_effect.per_share_nok, 2)} kr`}</strong>
          <small>{percentage(data.nav_effect?.pct, 2)} per aksje siden {dateLabel(program?.start_date)}</small>
        </article>
        <article className="card buybackKpi">
          <span className="label">Kjøpt siste uke</span>
          <strong>{count(latest?.shares)}</strong>
          <small>{dateLabel(latest?.period_start)}–{dateLabel(latest?.trade_date)}</small>
        </article>
        <article className="card buybackKpi">
          <span className="label">Volumandel siste uke</span>
          <strong>{value(latest?.volume_share_pct, 1)} %</strong>
          <small>av faktisk OTEC-handelsvolum</small>
        </article>
        <article className="card buybackKpi">
          <span className="label">Egne aksjer</span>
          <strong>{count(shares?.treasury_shares)}</strong>
          <small>{sourceLabel(shares?.treasury_source)} · {dateLabel(shares?.effective_from)}</small>
        </article>
        <article className="card buybackKpi">
          <span className="label">Utestående aksjer</span>
          <strong>{count(shares?.outstanding_shares)}</strong>
          <small>totalt {count(shares?.total_shares)}</small>
        </article>
      </section>

      <section className="buybackTwoCol">
        <article className="card buybackDetail">
          <div className="cardHeader">
            <div><span className="label">Siste rapporterte uke</span><h2>Faktisk gjennomføring</h2></div>
            <span className="pill">{dateLabel(latest?.trade_date)}</span>
          </div>
          <div className="buybackRows">
            <div><span>Kjøpte aksjer</span><strong>{count(latest?.shares)}</strong></div>
            <div><span>Gjennomsnittlig kjøpskurs</span><strong>{value(latest?.avg_price_nok, 2)} kr</strong></div>
            <div><span>Investert beløp</span><strong>{value(Number(latest?.amount_nok ?? 0) / 1_000_000, 2)} mill. kr</strong></div>
            <div><span>Markedsvolum i uken</span><strong>{count(latest?.market_volume_shares)}</strong></div>
            <div><span>Otellos volumandel</span><strong>{value(latest?.volume_share_pct, 2)} %</strong></div>
            <div><span>Safe Harbour-kapasitet</span><strong>{count(latest?.safe_harbour_capacity_shares)}</strong></div>
            <div><span>Utnyttet av estimert kapasitet</span><strong>{value(latest?.safe_harbour_utilization_pct, 1)} %</strong></div>
          </div>
        </article>

        <article className="card buybackDetail forecastCard">
          <div className="cardHeader">
            <div><span className="label">Neste uke</span><h2>Prognose</h2></div>
            <span className="buybackConfidence">{statusLabel(estimate?.confidence)}</span>
          </div>
          <div className="forecastPrimary">
            <span>Baseestimat</span>
            <strong>{count(estimate?.base_case_shares)}</strong>
            <small>
              {forecast?.forecast_week
                ? `${dateLabel(forecast.forecast_week.from)}–${dateLabel(forecast.forecast_week.to)}`
                : "Neste handelsuke"}
            </small>
          </div>
          <div className="forecastRange">
            <span>Lav</span><strong>{count(estimate?.low_shares)}</strong>
            <div className="rangeLine">
              <span className="rangeEstimate" />
              <span className="rangeBase" style={{ left: `${basePosition}%` }} aria-label="Baseestimat" />
            </div>
            <span>Høy</span><strong>{count(estimate?.high_shares)}</strong>
          </div>
          <div className="buybackRows compactRows">
            <div><span>ADV20</span><strong>{count(volume?.adv20_shares)}</strong></div>
            <div><span>Safe Harbour-kapasitet</span><strong>{count(volume?.week_start_capacity_estimate_shares)}</strong></div>
            <div><span>Maks kjøpspris</span><strong>{value(price?.program_cap_nok, 2)} kr</strong></div>
            <div><span>Avstand til maks kjøpspris</span><strong>{percentage(headroom, 1)}</strong></div>
          </div>
        </article>
      </section>

      <section className="buybackTwoCol programAndAccuracy">
        <article className="card buybackDetail">
          <div className="cardHeader"><div><span className="label">Programstatus</span><h2>Kapitalallokering</h2></div></div>
          <div className="buybackRows">
            <div><span>Kjøpt hittil</span><strong>{count(program?.cumulative_shares)}</strong></div>
            <div><span>Brukt hittil</span><strong>{value(Number(latest?.cumulative_program_amount_nok ?? 0) / 1_000_000, 1)} mill. kr</strong></div>
            <div><span>Gjenstående kapasitet</span><strong>{count(program?.remaining_shares)}</strong></div>
            <div><span>Program fremdrift</span><strong>{value(program?.progress_pct, 1)} %</strong></div>
            <div><span>Prisgrense</span><strong>{value(program?.max_price_nok, 2)} kr</strong></div>
            <div><span>Estimert ukentlig tempo</span><strong>{count(data.completion?.pace_shares_per_week)}</strong></div>
            <div><span>Estimert ferdigstillelse</span><strong>{dateLabel(data.completion?.estimated_completion_date)}</strong></div>
          </div>
        </article>

        <article className="card buybackDetail accuracyCard">
          <div className="cardHeader"><div><h2>Hvor godt treffer prognosen?</h2></div></div>
          <div className="accuracyGrid">
            <div><span>Uker testet</span><strong>{metrics?.weeks ?? 0}</strong></div>
            <div><span>Medianfeil</span><strong>{value(metrics?.median_ape_pct, 1)} %</strong></div>
            <div><span>Vektet feil</span><strong>{value(metrics?.wmape_pct, 1)} %</strong></div>
            <div><span>Innen ±10 %</span><strong>{value(metrics?.within_10_pct, 0)} %</strong></div>
            <div><span>Innen ±20 %</span><strong>{value(metrics?.within_20_pct, 0)} %</strong></div>
          </div>
          <p className="accuracyNote">Hver historisk uke beregnes med kun informasjon som var tilgjengelig før uken startet.</p>
        </article>
      </section>

      <section className="card buybackHistory">
        <div className="cardHeader">
          <div><span className="label">Historisk prognose mot faktisk</span><h2>Siste modellerte uker</h2></div>
          <span className="pill muted">{weeks.length} UKER</span>
        </div>
        {weeks.length ? (
          <div className="buybackTableWrap">
            <table className="buybackTable">
              <thead>
                <tr>
                  <th>Uke</th>
                  <th>Faktisk</th>
                  <th>Prognose</th>
                  <th>Avvik</th>
                  <th>Volumandel</th>
                  <th>Safe Harbour-utnyttelse</th>
                </tr>
              </thead>
              <tbody>
                {weeks.map((week) => {
                  const error = week.forecast_error_pct;
                  return (
                    <tr key={week.period_end}>
                      <td>{dateLabel(week.period_start)}–{dateLabel(week.period_end)}</td>
                      <td>{count(week.actual_shares)}</td>
                      <td>{count(Math.round(week.walk_forward_prediction_shares))}</td>
                      <td className={error == null ? "" : Math.abs(error) <= 10 ? "tableGood" : Math.abs(error) <= 20 ? "tableMid" : "tableBad"}>
                        {error == null ? "–" : `${error > 0 ? "+" : ""}${value(error, 1)} %`}
                      </td>
                      <td>{value(week.actual_volume_share_pct, 1)} %</td>
                      <td>{value(week.safe_harbour_utilization_pct, 1)} %</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="buybackEmpty">Ikke nok historikk til å vise walk-forward-test ennå.</div>
        )}
        <div className="buybackMethodNote">{data.methodology_note}</div>
      </section>
    </div>
  );
}

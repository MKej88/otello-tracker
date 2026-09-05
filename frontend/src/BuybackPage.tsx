import { useEffect, useMemo, useState } from "react";
import { fetchPreloadedJson } from "./navigationDataPreload";
import ResourceNotice from "./ResourceNotice";
import "./buyback-page.css";

type Program = {
  external_id?: string;
  start_date?: string | null;
  end_date?: string | null;
  max_shares?: number | null;
  cumulative_shares?: number | null;
  remaining_shares?: number | null;
  average_purchase_price_nok?: string | number | null;
  max_price_nok?: number | null;
  progress_pct?: number | null;
  cash_spent_nok?: string | number | null;
  vwap_nok?: string | number | null;
  share_count_nav_effect_per_share_nok?: number | null;
  share_count_nav_effect_pct?: number | null;
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

type BemobiDashboard = {
  ready?: boolean;
  otello?: {
    shares?: number | null;
    ownership_pct?: number | null;
  };
};

const AUTO_REFRESH_MS = 2 * 60 * 1000;
const BEMOBI_REFRESH_MS = 30 * 60 * 1000;
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

function finiteNumber(input: number | string | null | undefined) {
  if (input == null || input === "") return null;
  const numeric = Number(input);
  return Number.isFinite(numeric) ? numeric : null;
}

function signedKr(input: number | null | undefined, digits = 2) {
  if (input == null || !Number.isFinite(input)) return "–";
  return `${input > 0 ? "+" : ""}${value(input, digits)} kr`;
}

function signedPercentage(input: number | null | undefined, digits = 2) {
  if (input == null || !Number.isFinite(input)) return "–";
  return `${input > 0 ? "+" : ""}${value(input, digits)} %`;
}

function effectTone(input: number | null | undefined) {
  if (input == null || !Number.isFinite(input) || input === 0) return "neutral";
  return input > 0 ? "positive" : "negative";
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

function osloDateKey(now = new Date()) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/Oslo",
    year: "numeric",
    month: "2-digit",
    day: "2-digit"
  }).formatToParts(now);
  const year = parts.find((part) => part.type === "year")?.value;
  const month = parts.find((part) => part.type === "month")?.value;
  const day = parts.find((part) => part.type === "day")?.value;
  return year && month && day ? `${year}-${month}-${day}` : null;
}

function weekStartKey(input?: string | null) {
  if (!input || !/^\d{4}-\d{2}-\d{2}$/.test(input)) return null;
  const date = new Date(`${input}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return null;
  const weekday = date.getUTCDay() || 7;
  date.setUTCDate(date.getUTCDate() - weekday + 1);
  return date.toISOString().slice(0, 10);
}

function addDaysKey(input: string, days: number) {
  const date = new Date(`${input}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function forecastPeriodLabel(week?: ForecastWeek) {
  const currentWeek = weekStartKey(osloDateKey());
  const forecastWeek = weekStartKey(week?.from);
  if (!currentWeek || !forecastWeek) return "Kommende uke";
  if (forecastWeek === currentWeek) return "Denne uken";
  if (forecastWeek === addDaysKey(currentWeek, 7)) return "Neste uke";
  return forecastWeek > currentWeek ? "Kommende uke" : "Siste prognose";
}

export default function BuybackPage() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [failed, setFailed] = useState(false);
  const [bemobi, setBemobi] = useState<BemobiDashboard | null>(null);

  useEffect(() => {
    let active = true;
    const load = () => {
      fetchPreloadedJson<Dashboard>("/api/buybacks/dashboard")
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

  useEffect(() => {
    let active = true;
    const load = () => {
      fetch("/api/bemobi/dashboard")
        .then((response) => {
          if (!response.ok) throw new Error("Bemobi dashboard API-feil");
          return response.json() as Promise<BemobiDashboard>;
        })
        .then((result) => {
          if (active) setBemobi(result);
        })
        .catch(() => {
          // Bemobi-eksponering er et supplement og skal aldri blokkere buyback-siden.
        });
    };
    load();
    const timer = window.setInterval(load, BEMOBI_REFRESH_MS);
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
  const programCashSpent = finiteNumber(program?.cash_spent_nok)
    ?? finiteNumber(latest?.cumulative_program_amount_nok);
  const programVwap = finiteNumber(program?.vwap_nok)
    ?? finiteNumber(program?.average_purchase_price_nok);
  const bemobiShares = bemobi?.ready === false ? null : bemobi?.otello?.shares;
  const bemobiPerThousandOtec = bemobiShares != null
    && Number.isFinite(bemobiShares)
    && shares?.outstanding_shares != null
    && shares.outstanding_shares > 0
      ? bemobiShares / shares.outstanding_shares * 1000
      : null;
  const navEffect = data?.nav_effect?.per_share_nok;
  const navEffectPct = data?.nav_effect?.pct;
  const grossShareEffect = program?.share_count_nav_effect_per_share_nok;
  const grossShareEffectPct = program?.share_count_nav_effect_pct;

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
      <section className="buybackHero card investorBuybackHero">
        <div className="buybackHeroCopy">
          <span className="label">Verdiskaping fra tilbakekjøp</span>
          <div className="buybackHeroTitle">
            <h2 className={effectTone(navEffect)}>
              {navEffect == null ? "Netto NAV-effekt beregnes" : `${signedKr(navEffect, 2)} NAV / aksje`}
            </h2>
            <span className={`buybackStatus ${data.status === "OK" ? "ok" : "warn"}`}>
              {statusLabel(data.status)}
            </span>
          </div>
          <p>
            Nettoeffekten måler hvor mye dagens program har endret NAV per gjenværende OTEC-aksje etter
            at kontantene brukt på tilbakekjøp er trukket fra. Bruttoeffekten fra færre aksjer alene er
            {grossShareEffect == null ? " ikke tilgjengelig ennå" : ` ${signedKr(grossShareEffect, 2)} per aksje`}.
          </p>
          <div className="buybackProgressTrack" aria-label={`Programmet er ${value(progress, 1)} prosent fullført`}>
            <span style={{ width: `${progress}%` }} />
          </div>
          <div className="buybackProgressLabels">
            <strong>{value(progress, 1)} % av programmet gjennomført</strong>
            <span>{count(program?.cumulative_shares)} kjøpt · {count(program?.remaining_shares)} gjenstår</span>
          </div>
        </div>
        <div className="buybackHeroMetric">
          <span>Netto NAV-effekt</span>
          <strong className={effectTone(navEffectPct)}>{signedPercentage(navEffectPct, 2)}</strong>
          <small>siden {dateLabel(program?.start_date)}</small>
          <em>{completionText(data.completion)}</em>
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

      <section className="buybackKpis investorBuybackKpis">
        <article className="card buybackKpi navEffectKpi">
          <span className="label">Brutto effekt av færre aksjer</span>
          <strong>{signedKr(grossShareEffect, 2)}</strong>
          <small>{signedPercentage(grossShareEffectPct, 2)} før kontantbruken i programmet</small>
        </article>
        <article className="card buybackKpi">
          <span className="label">Kapital brukt hittil</span>
          <strong>{programCashSpent == null ? "–" : `${value(Math.abs(programCashSpent) / 1_000_000, 1)} mill. kr`}</strong>
          <small>{count(program?.cumulative_shares)} OTEC-aksjer kjøpt tilbake</small>
        </article>
        <article className="card buybackKpi">
          <span className="label">Gjennomsnittlig kjøpskurs</span>
          <strong>{programVwap == null ? "–" : `${value(programVwap, 2)} kr`}</strong>
          <small>volumvektet pris for dagens program</small>
        </article>
        <article className="card buybackKpi bemobiExposureKpi">
          <span className="label">Bemobi per 1 000 OTEC</span>
          <strong>{bemobiPerThousandOtec == null ? "–" : value(bemobiPerThousandOtec, 1)}</strong>
          <small>
            indirekte BMOB3-aksjer per 1 000 utestående OTEC
            {bemobi?.otello?.ownership_pct == null ? "" : ` · Otello eier ${value(bemobi.otello.ownership_pct, 2)} %`}
          </small>
        </article>
        <article className="card buybackKpi">
          <span className="label">Utestående OTEC-aksjer</span>
          <strong>{count(shares?.outstanding_shares)}</strong>
          <small>{count(shares?.treasury_shares)} egne aksjer holdes av selskapet</small>
        </article>
      </section>

      <div className="buybackInvestorNote">
        <strong>Slik leses effekten:</strong>
        <span>
          Brutto aksjeantallseffekt viser verdien av at samme egenkapital fordeles på færre aksjer før
          kontantbruken. Netto NAV-effekt inkluderer også kontantene som faktisk er brukt på kjøpene.
          Bemobi-eksponeringen viser dagens indirekte beholdning per 1 000 OTEC og er kun et supplement.
        </span>
      </div>

      <div className="buybackSectionIntro">
        <span className="label">Gjennomføring</span>
        <h2>Hvordan programmet faktisk gjennomføres</h2>
        <p>Handelsdata, tempo og prognose ligger under verdiskapingen slik at investorperspektivet kommer først.</p>
      </div>

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
            <div><span className="label">{forecastPeriodLabel(forecast?.forecast_week)}</span><h2>Prognose</h2></div>
            <span className="buybackConfidence">{statusLabel(estimate?.confidence)}</span>
          </div>
          <div className="forecastPrimary">
            <span>Baseestimat</span>
            <strong>{count(estimate?.base_case_shares)}</strong>
            <small>
              {forecast?.forecast_week
                ? `${dateLabel(forecast.forecast_week.from)}–${dateLabel(forecast.forecast_week.to)}`
                : "Prognoseperiode ikke oppgitt"}
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
            <div><span>Brukt hittil</span><strong>{programCashSpent == null ? "–" : `${value(Math.abs(programCashSpent) / 1_000_000, 1)} mill. kr`}</strong></div>
            <div><span>Gjennomsnittlig kjøpskurs</span><strong>{programVwap == null ? "–" : `${value(programVwap, 2)} kr`}</strong></div>
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

import { useEffect, useMemo, useState } from "react";
import "./shareholders-page.css";

type ShareCount = {
  effective_from?: string | null;
  total_shares?: number | null;
  treasury_shares?: number | null;
  outstanding_shares?: number | null;
  source_url?: string | null;
  source_code?: string | null;
};

type HoldingRow = {
  rank: number;
  shareholder_name: string;
  country?: string | null;
  shares: number;
  ownership_pct?: string | number | null;
  account_type?: string | null;
};

type ChangeRow = {
  shareholder_name: string;
  current_shares: number;
  previous_shares: number;
  change_shares: number;
  current_rank?: number | null;
  previous_rank?: number | null;
  new_in_top20: boolean;
  exited_top20: boolean;
};

type Snapshot = {
  id: number;
  snapshot_date: string;
  source_kind: string;
  captured_at?: string | null;
  row_count: number;
  top20_shares: number;
  top20_pct?: number | null;
};

type DailySummary = {
  status: "NO_SNAPSHOT" | "FIRST_SNAPSHOT" | "NO_CHANGES" | "CHANGES" | string;
  message: string;
  latest_date?: string | null;
  previous_date?: string | null;
  is_previous_day: boolean;
  change_count: number;
};

type ShareholderPayload = {
  ready: boolean;
  official_live: {
    title: string;
    updated_frequency: string;
    source: string;
    source_page_url: string;
    embed_url: string;
  };
  shareholder_identification: {
    as_of_date: string;
    source: string;
    url: string;
    format: string;
  };
  share_count?: ShareCount | null;
  history: {
    snapshot_count: number;
    comparison_ready: boolean;
    snapshots: Snapshot[];
    latest_rows: HoldingRow[];
    daily_summary?: DailySummary | null;
    movement?: {
      changes: ChangeRow[];
      biggest_buyers: ChangeRow[];
      biggest_sellers: ChangeRow[];
      new_entries: ChangeRow[];
      exits: ChangeRow[];
    } | null;
    note: string;
  };
};

const integer = new Intl.NumberFormat("nb-NO", { maximumFractionDigits: 0 });

function pct(input: number | null | undefined, digits = 1) {
  if (input == null || !Number.isFinite(input)) return "–";
  return `${input.toLocaleString("nb-NO", { minimumFractionDigits: digits, maximumFractionDigits: digits })} %`;
}

function ownershipLabel(input: string | number | null | undefined) {
  if (input == null || input === "") return "–";
  const numeric = Number(input);
  return Number.isFinite(numeric) ? pct(numeric, 2) : String(input);
}

function dateLabel(input?: string | null) {
  if (!input) return "–";
  const [year, month, day] = input.slice(0, 10).split("-");
  return year && month && day ? `${day}.${month}.${year}` : input;
}

function changeLabel(value: number) {
  return `${value > 0 ? "+" : ""}${integer.format(value)}`;
}

function changeClass(value: number) {
  return value > 0 ? "positive" : value < 0 ? "negative" : "";
}

function rankLabel(row: ChangeRow) {
  if (row.new_in_top20) return "Ny i Top 20";
  if (row.exited_top20) return "Ut av Top 20";
  if (row.previous_rank != null && row.current_rank != null && row.previous_rank !== row.current_rank) {
    return `#${row.previous_rank} → #${row.current_rank}`;
  }
  return row.current_rank != null ? `#${row.current_rank}` : "";
}

export default function ShareholdersPage() {
  const [data, setData] = useState<ShareholderPayload | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    const load = () => {
      fetch("/api/shareholders/dashboard")
        .then((response) => {
          if (!response.ok) throw new Error("Aksjonær-API-feil");
          return response.json() as Promise<ShareholderPayload>;
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
    const timer = window.setInterval(load, 5 * 60 * 1000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  const changeByName = useMemo(() => {
    const map = new Map<string, ChangeRow>();
    for (const row of data?.history.movement?.changes ?? []) map.set(row.shareholder_name, row);
    return map;
  }, [data]);

  if (!data && !failed) return <div className="shareholdersNotice">Laster aksjonærdata …</div>;
  if (!data) return <div className="shareholdersNotice"><strong>Kunne ikke hente aksjonærdata.</strong></div>;

  const history = data.history;
  const count = data.share_count;
  const latestSnapshot = history.snapshots[0];
  const movement = history.movement;
  const daily = history.daily_summary;

  return (
    <div className="shareholdersPage">
      <section className="card shareholdersHero">
        <div>
          <span className="label">OTEC / AKSJONÆRER</span>
          <h2>Hvem eier Otello?</h2>
          <p>Offisiell Top 20 fra Otello/Euronext, hentet inn i trackeren hver dag og sammenlignet med forrige dags måling.</p>
        </div>
        <a className="shareholdersSourceButton" href={data.official_live.embed_url} target="_blank" rel="noreferrer">
          Åpne originalkilden
        </a>
      </section>

      <section className="shareholdersKpis">
        <article className="card">
          <span className="label">Utstedte aksjer</span>
          <strong>{count?.total_shares != null ? integer.format(count.total_shares) : "–"}</strong>
          <small>{dateLabel(count?.effective_from)}</small>
        </article>
        <article className="card">
          <span className="label">Egne aksjer</span>
          <strong>{count?.treasury_shares != null ? integer.format(count.treasury_shares) : "–"}</strong>
          <small>Holdes utenfor utestående</small>
        </article>
        <article className="card">
          <span className="label">Utestående aksjer</span>
          <strong>{count?.outstanding_shares != null ? integer.format(count.outstanding_shares) : "–"}</strong>
          <small>Trackerens siste aksjegrunnlag</small>
        </article>
        <article className="card">
          <span className="label">Top 20-andel</span>
          <strong>{latestSnapshot ? pct(latestSnapshot.top20_pct) : "–"}</strong>
          <small>{history.snapshot_count ? `${history.snapshot_count} daglige målinger` : "Venter på første måling"}</small>
        </article>
      </section>

      <section className="card top20NativeCard">
        <div className="cardHeader shareholdersHeader">
          <div>
            <span className="label">OFFISIELL · HENTES DAGLIG</span>
            <h2>Top 20 største aksjonærer</h2>
          </div>
          <div className="shareholdersSnapshotDate">
            <span>Siste måling</span>
            <strong>{dateLabel(latestSnapshot?.snapshot_date)}</strong>
          </div>
        </div>

        {daily && (
          <div className={`dailyChangeSummary dailyChange-${daily.status.toLowerCase()}`}>
            <span className="dailyChangeDot" />
            <div>
              <strong>{daily.message}</strong>
              {daily.previous_date && !daily.is_previous_day && (
                <small>Forrige tilgjengelige måling: {dateLabel(daily.previous_date)}</small>
              )}
            </div>
          </div>
        )}

        {history.latest_rows.length === 0 ? (
          <div className="shareholdersEmpty">
            <strong>Venter på første Top 20-snapshot.</strong>
            <span>Listen vises her så snart den daglige Euronext-innhentingen har lagret en komplett måling.</span>
          </div>
        ) : (
          <div className="shareholdersTableWrap top20TableWrap">
            <table className="top20Table">
              <thead>
                <tr><th>#</th><th>Aksjonær</th><th>Land</th><th>Aksjer</th><th>Andel</th><th>Endring</th></tr>
              </thead>
              <tbody>
                {history.latest_rows.map((row) => {
                  const change = changeByName.get(row.shareholder_name);
                  return (
                    <tr key={`${row.rank}-${row.shareholder_name}`}>
                      <td className="rankCell">{row.rank}</td>
                      <td className="shareholderNameCell">{row.shareholder_name}</td>
                      <td>{row.country ?? "–"}</td>
                      <td>{integer.format(row.shares)}</td>
                      <td>{ownershipLabel(row.ownership_pct)}</td>
                      <td>
                        {change?.new_in_top20 ? (
                          <span className="changeBadge positive">Ny</span>
                        ) : change ? (
                          <strong className={changeClass(change.change_shares)}>{changeLabel(change.change_shares)}</strong>
                        ) : (
                          <span className="mutedText">–</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        <p className="shareholdersFootnote">{history.note}</p>
      </section>

      <section className="shareholdersTwoCol">
        <article className="card">
          <div className="cardHeader">
            <div><span className="label">DAGLIG SAMMENLIGNING</span><h2>Endringer</h2></div>
            <span className="pill">{history.comparison_ready ? `${daily?.change_count ?? 0} endringer` : "Venter"}</span>
          </div>
          {!history.comparison_ready ? (
            <div className="shareholdersEmpty">
              <strong>Sammenligning trenger to dagsmålinger.</strong>
              <span>Etter neste lagrede snapshot vises alle endringer automatisk.</span>
            </div>
          ) : (
            <ChangeList rows={movement?.changes ?? []} />
          )}
        </article>

        <article className="card">
          <div className="cardHeader">
            <div><span className="label">KONTROLLKILDE</span><h2>Aksjonæridentifikasjon</h2></div>
          </div>
          <div className="shareholdersInfoRows">
            <div><span>Dato</span><strong>{dateLabel(data.shareholder_identification.as_of_date)}</strong></div>
            <div><span>Kilde</span><strong>{data.shareholder_identification.source}</strong></div>
            <div><span>Format</span><strong>{data.shareholder_identification.format}</strong></div>
          </div>
          <a className="shareholdersTextLink" href={data.shareholder_identification.url} target="_blank" rel="noreferrer">
            Åpne Otellos aksjonæridentifikasjon
          </a>
        </article>
      </section>
    </div>
  );
}

function ChangeList({ rows }: { rows: ChangeRow[] }) {
  if (rows.length === 0) {
    return <div className="shareholdersNoChanges"><strong>Ingen endringer</strong><span>Top 20 er identisk med forrige måling.</span></div>;
  }

  return (
    <div className="dailyChangesList">
      {rows.map((row) => (
        <div className="dailyChangeRow" key={row.shareholder_name}>
          <div>
            <strong>{row.shareholder_name}</strong>
            <small>{rankLabel(row)}</small>
          </div>
          <div className="dailyChangeNumbers">
            {row.new_in_top20 ? (
              <span className="changeBadge positive">Ny i Top 20</span>
            ) : row.exited_top20 ? (
              <span className="changeBadge negative">Ut av Top 20</span>
            ) : (
              <strong className={changeClass(row.change_shares)}>{changeLabel(row.change_shares)} aksjer</strong>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

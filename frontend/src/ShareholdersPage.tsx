import { useEffect, useState } from "react";
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
  row_count: number;
  top20_shares: number;
  top20_pct?: number | null;
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
    movement?: {
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

function dateLabel(input?: string | null) {
  if (!input) return "–";
  const [year, month, day] = input.split("-");
  return year && month && day ? `${day}.${month}.${year}` : input;
}

function changeLabel(value: number) {
  return `${value > 0 ? "+" : ""}${integer.format(value)}`;
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

  if (!data && !failed) return <div className="shareholdersNotice">Laster aksjonærdata …</div>;
  if (!data) return <div className="shareholdersNotice"><strong>Kunne ikke hente aksjonærdata.</strong></div>;

  const history = data.history;
  const count = data.share_count;
  const latestSnapshot = history.snapshots[0];
  const movement = history.movement;

  return (
    <div className="shareholdersPage">
      <section className="card shareholdersHero">
        <div>
          <span className="label">OTEC / AKSJONÆRER</span>
          <h2>Hvem eier Otello?</h2>
          <p>Offisiell Top 20 fra Otello/Euronext, kombinert med trackerens egne snapshots for å se akkumulering og reduksjon over tid.</p>
        </div>
        <a className="shareholdersSourceButton" href={data.official_live.source_page_url} target="_blank" rel="noreferrer">
          Offisiell kilde
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
          <small>{history.snapshot_count ? `${history.snapshot_count} lagrede snapshots` : "Historikk starter med første snapshot"}</small>
        </article>
      </section>

      <section className="card liveTop20Card">
        <div className="cardHeader shareholdersHeader">
          <div>
            <span className="label">OFFISIELL · OPPDATERES UKENTLIG</span>
            <h2>Top 20 største aksjonærer</h2>
          </div>
          <a href={data.official_live.embed_url} target="_blank" rel="noreferrer" className="pill">Åpne hos Euronext</a>
        </div>
        <div className="top20FrameWrap">
          <iframe
            className="top20Frame"
            src={data.official_live.embed_url}
            title="Otello Top 20 largest shareholders"
            loading="lazy"
          />
        </div>
        <p className="shareholdersFootnote">
          Hvis Euronext blokkerer innbygging i nettleseren, bruk «Åpne hos Euronext». Listen er Otellos offisielle Top 20-kilde.
        </p>
      </section>

      <section className="shareholdersTwoCol">
        <article className="card">
          <div className="cardHeader">
            <div><span className="label">TRACKER</span><h2>Uke-for-uke</h2></div>
            <span className="pill">{history.comparison_ready ? "Klar" : "Venter"}</span>
          </div>
          {!history.comparison_ready ? (
            <div className="shareholdersEmpty">
              <strong>Historikken er klargjort.</strong>
              <span>Når to Top 20-snapshots er lagret, vises største kjøpere, selgere, nye navn og utgående navn automatisk.</span>
            </div>
          ) : (
            <div className="movementGrid">
              <MovementList title="Største kjøpere" rows={movement?.biggest_buyers ?? []} />
              <MovementList title="Største selgere" rows={movement?.biggest_sellers ?? []} />
            </div>
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

      {history.latest_rows.length > 0 && (
        <section className="card shareholdersStoredTable">
          <div className="cardHeader">
            <div><span className="label">SIST LAGRET</span><h2>Tracker-snapshot {dateLabel(latestSnapshot?.snapshot_date)}</h2></div>
          </div>
          <div className="shareholdersTableWrap">
            <table>
              <thead><tr><th>#</th><th>Aksjonær</th><th>Land</th><th>Aksjer</th><th>Andel</th></tr></thead>
              <tbody>
                {history.latest_rows.map((row) => (
                  <tr key={`${row.rank}-${row.shareholder_name}`}>
                    <td>{row.rank}</td>
                    <td>{row.shareholder_name}</td>
                    <td>{row.country ?? "–"}</td>
                    <td>{integer.format(row.shares)}</td>
                    <td>{row.ownership_pct ?? "–"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}

function MovementList({ title, rows }: { title: string; rows: ChangeRow[] }) {
  return (
    <div className="movementList">
      <h3>{title}</h3>
      {rows.length === 0 ? <span className="mutedText">Ingen endringer</span> : rows.map((row) => (
        <div key={row.shareholder_name}>
          <span>{row.shareholder_name}</span>
          <strong className={row.change_shares >= 0 ? "positive" : "negative"}>{changeLabel(row.change_shares)}</strong>
        </div>
      ))}
    </div>
  );
}

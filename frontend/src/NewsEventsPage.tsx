import { useMemo, useState } from "react";
import { usePollingResource } from "./usePollingResource";
import { formatDate, formatDateTime } from "./uiFormat";
import "./news-events.css";

const REFRESH_MS = 5 * 60 * 1000;
type Importance = "HIGH" | "MEDIUM" | "LOW";
type CompanyFilter = "Alle" | "Otello" | "Bemobi";
type ContentType = "OFFICIAL" | "MEDIA";
type ContentFilter = "Alle typer" | "Offisielt" | "Media";
type NewsItem = {
  id: number;
  company: "Otello" | "Bemobi";
  headline: string;
  published_at?: string | null;
  category_label: string;
  importance: Importance;
  summary?: string | null;
  source?: string | null;
  url?: string | null;
  content_type?: ContentType;
  original_language?: string | null;
};
type EventItem = { id: string; date: string; company: "Otello" | "Bemobi"; title: string; importance: Importance; date_label: string; confirmed: boolean; source?: string | null; url?: string | null };
type MediaStatus = {
  available?: boolean;
  status?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  feeds_checked?: number;
  candidates?: number;
  written?: number;
  skipped_existing?: number;
  error_count?: number;
  initial_backfill?: boolean;
  window_days?: number;
  error_message?: string | null;
};
type Payload = { ready: boolean; news?: NewsItem[]; events?: EventItem[]; counts?: { news?: number; events?: number }; media_status?: MediaStatus };
const importanceLabels: Record<Importance, string> = { HIGH: "Høy", MEDIUM: "Middels", LOW: "Lav" };

function dateLabel(input?: string | null, includeTime = false) {
  if (!input) return "Dato mangler";
  return includeTime ? formatDateTime(input) : formatDate(input);
}
function SourceLink({ url, source }: { url?: string | null; source?: string | null }) {
  if (!url) return <span className="newsSource">{source ?? "Kilde ikke oppgitt"}</span>;
  return <a className="newsSourceLink" href={url} target="_blank" rel="noreferrer">Åpne hos {source ?? "originalkilden"} <span aria-hidden="true">↗</span></a>;
}
function ImportanceBadge({ importance }: { importance: Importance }) {
  return <span className={`importanceBadge importance${importance}`}>{importanceLabels[importance]}</span>;
}
function contentType(item: NewsItem): ContentType {
  return item.content_type === "MEDIA" ? "MEDIA" : "OFFICIAL";
}
function matchesContentFilter(item: NewsItem, filter: ContentFilter) {
  if (filter === "Alle typer") return true;
  return filter === "Media" ? contentType(item) === "MEDIA" : contentType(item) === "OFFICIAL";
}
function mediaStatusLabel(status?: string | null) {
  if (status === "SUCCESS") return "OK";
  if (status === "PARTIAL") return "Delvis";
  if (status === "FAILED") return "Feil";
  if (status === "RUNNING") return "Kjører";
  return "Ikke kjørt";
}
function mediaStatusClass(status?: string | null) {
  if (status === "SUCCESS") return "mediaStatusSuccess";
  if (status === "PARTIAL") return "mediaStatusPartial";
  if (status === "FAILED") return "mediaStatusFailed";
  return "mediaStatusNeutral";
}

export default function NewsEventsPage() {
  const { data, refreshFailed } = usePollingResource<Payload>(
    "/api/news-events",
    REFRESH_MS,
    true,
  );
  const [company, setCompany] = useState<CompanyFilter>("Alle");
  const [contentFilter, setContentFilter] = useState<ContentFilter>("Alle typer");
  const news = useMemo(() => (data?.news ?? []).filter((item) => (
    (company === "Alle" || item.company === company) && matchesContentFilter(item, contentFilter)
  )), [company, contentFilter, data?.news]);
  const events = useMemo(() => (data?.events ?? []).filter((item) => company === "Alle" || item.company === company), [company, data?.events]);
  const mediaStatus = data?.media_status;
  const mediaCheckedAt = mediaStatus?.finished_at ?? mediaStatus?.started_at;
  return (
    <div className="investorPage newsEventsPage">
      <section className="card newsHero">
        <div>
          <span className="label">NYHETER OG KALENDER</span>
          <h2>Det viktigste rundt Otello og Bemobi</h2>
          <p>Offisielle meldinger, relevant medieomtale og kjente datoer. Portugisisk Bemobi-omtale vises med automatisk engelsk oversettelse av tilgjengelig RSS-metadata; originalkilden er alltid tilgjengelig.</p>
        </div>
        <div className="newsHeroStats"><div><strong>{data?.counts?.news ?? "–"}</strong><span>meldinger</span></div><div><strong>{data?.counts?.events ?? "–"}</strong><span>kommende datoer</span></div>{refreshFailed && <small>Viser siste gode data</small>}</div>
      </section>
      <section className="newsToolbar" aria-label="Filtrer innhold">
        <div className="newsFilterGroup">
          <span className="newsFilterLabel">Selskap</span>
          <div className="newsFilterButtons">
            {(["Alle", "Otello", "Bemobi"] as CompanyFilter[]).map((item) => <button className={company === item ? "periodButton active" : "periodButton"} key={item} onClick={() => setCompany(item)} type="button">{item}</button>)}
          </div>
        </div>
        <div className="newsFilterGroup">
          <span className="newsFilterLabel">Type</span>
          <div className="newsFilterButtons">
            {(["Alle typer", "Offisielt", "Media"] as ContentFilter[]).map((item) => <button className={contentFilter === item ? "periodButton active" : "periodButton"} key={item} onClick={() => setContentFilter(item)} type="button">{item}</button>)}
          </div>
        </div>
      </section>
      <section className={`card mediaRefreshStatus ${mediaStatusClass(mediaStatus?.status)}`} aria-label="Status for medieinnhenting">
        <div className="mediaRefreshLead">
          <div><span className="label">MEDIAINNHENTING</span><strong>{mediaStatusLabel(mediaStatus?.status)}</strong></div>
          <p>{mediaStatus?.available ? <>Sist sjekket {dateLabel(mediaCheckedAt, true)} · {mediaStatus.window_days ?? 30} dagers søkevindu{mediaStatus.initial_backfill ? " · første backfill" : ""}</> : <>Venter på første mediekjøring. Google News søker de siste {mediaStatus?.window_days ?? 30} dagene.</>}</p>
        </div>
        <div className="mediaRefreshMetrics" aria-label="Resultat fra siste mediekjøring">
          <span><strong>{mediaStatus?.feeds_checked ?? "–"}</strong> feeds</span>
          <span><strong>{mediaStatus?.candidates ?? "–"}</strong> kandidater</span>
          <span><strong>{mediaStatus?.written ?? "–"}</strong> nye</span>
          <span><strong>{mediaStatus?.error_count ?? "–"}</strong> feil</span>
        </div>
        {mediaStatus?.error_message && <small className="mediaRefreshError">{mediaStatus.error_message}</small>}
      </section>
      <section className="newsLayout">
        <div className="newsColumn">
          <div className="sectionHeading"><div><span className="label">SISTE MELDINGER</span><h2>Nyheter</h2></div><span className="pill">{news.length} VIST</span></div>
          {!data && <article className="card emptyNewsCard">Laster meldinger …</article>}
          {data && news.length === 0 && <article className="card emptyNewsCard">Ingen meldinger funnet for dette filteret.</article>}
          <div className="newsList">
            {news.map((item) => {
              const itemType = contentType(item);
              return (
                <article className="card newsCard" key={item.id}>
                  <div className="newsMeta">
                    <span className={`companyTag company${item.company}`}>{item.company}</span>
                    <span className={`contentTypeBadge content${itemType}`}>{itemType === "MEDIA" ? "Media" : "Official"}</span>
                    <span>{item.category_label}</span>
                    <ImportanceBadge importance={item.importance} />
                  </div>
                  <h3>{item.headline}</h3>
                  {item.summary && <p>{item.summary}</p>}
                  {itemType === "MEDIA" && item.original_language && <span className="translationNote">Automatically translated from Portuguese · RSS metadata</span>}
                  <div className="newsCardFooter"><time dateTime={item.published_at ?? undefined}>{dateLabel(item.published_at, true)}</time><SourceLink source={item.source} url={item.url} /></div>
                </article>
              );
            })}
          </div>
        </div>
        <aside className="calendarColumn">
          <div className="sectionHeading"><div><span className="label">FREMOVER</span><h2>Hendelseskalender</h2></div></div>
          <div className="card calendarCard">
            {!data && <p className="emptyCalendar">Laster kalender …</p>}
            {data && events.length === 0 && <p className="emptyCalendar">Ingen kjente kommende datoer for dette filteret.</p>}
            {events.map((item) => <div className="calendarEvent" key={item.id}><time dateTime={item.date}><strong>{formatDate(item.date)}</strong></time><div><div className="newsMeta"><span className={`companyTag company${item.company}`}>{item.company}</span><ImportanceBadge importance={item.importance} /></div><h3>{item.title}</h3><p>{item.date_label} · {item.confirmed ? "Bekreftet" : "Forventet / ikke bekreftet"}</p><SourceLink source={item.source} url={item.url} /></div></div>)}
          </div>
          <p className="calendarNote">Forventede datoer er tydelig merket og kan endres. Kontroller alltid originalkilden.</p>
        </aside>
      </section>
    </div>
  );
}

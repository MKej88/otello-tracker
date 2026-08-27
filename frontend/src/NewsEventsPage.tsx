import { useMemo, useState } from "react";
import { usePollingResource } from "./usePollingResource";
import "./news-events.css";

const REFRESH_MS = 5 * 60 * 1000;
type Importance = "HIGH" | "MEDIUM" | "LOW";
type CompanyFilter = "Alle" | "Otello" | "Bemobi";
type NewsItem = { id: number; company: "Otello" | "Bemobi"; headline: string; published_at?: string | null; category_label: string; importance: Importance; summary?: string | null; source?: string | null; url?: string | null };
type EventItem = { id: string; date: string; company: "Otello" | "Bemobi"; title: string; importance: Importance; date_label: string; confirmed: boolean; source?: string | null; url?: string | null };
type Payload = { ready: boolean; news?: NewsItem[]; events?: EventItem[]; counts?: { news?: number; events?: number } };
const importanceLabels: Record<Importance, string> = { HIGH: "Høy", MEDIUM: "Middels", LOW: "Lav" };

function dateLabel(input?: string | null, includeTime = false) {
  if (!input) return "Dato mangler";
  const parsed = new Date(input);
  if (Number.isNaN(parsed.getTime())) return input;
  return parsed.toLocaleDateString("nb-NO", { day: "2-digit", month: "short", year: "numeric", ...(includeTime ? { hour: "2-digit", minute: "2-digit" } : {}) });
}
function SourceLink({ url, source }: { url?: string | null; source?: string | null }) {
  if (!url) return <span className="newsSource">{source ?? "Kilde ikke oppgitt"}</span>;
  return <a className="newsSourceLink" href={url} target="_blank" rel="noreferrer">Åpne hos {source ?? "originalkilden"} <span aria-hidden="true">↗</span></a>;
}
function ImportanceBadge({ importance }: { importance: Importance }) {
  return <span className={`importanceBadge importance${importance}`}>{importanceLabels[importance]}</span>;
}

export default function NewsEventsPage() {
  const { data, refreshFailed } = usePollingResource<Payload>("/api/news-events", REFRESH_MS);
  const [company, setCompany] = useState<CompanyFilter>("Alle");
  const news = useMemo(() => (data?.news ?? []).filter((item) => company === "Alle" || item.company === company), [company, data?.news]);
  const events = useMemo(() => (data?.events ?? []).filter((item) => company === "Alle" || item.company === company), [company, data?.events]);
  return (
    <div className="investorPage newsEventsPage">
      <section className="card newsHero">
        <div><span className="label">NYHETER OG KALENDER</span><h2>Det viktigste rundt Otello og Bemobi</h2><p>Offentlige meldinger og kjente datoer samlet uten automatisk KI-tolkning. Sammendrag vises bare når det finnes et faktabasert sammendrag i datakilden.</p></div>
        <div className="newsHeroStats"><div><strong>{data?.counts?.news ?? "–"}</strong><span>meldinger</span></div><div><strong>{data?.counts?.events ?? "–"}</strong><span>kommende datoer</span></div>{refreshFailed && <small>Viser siste gode data</small>}</div>
      </section>
      <section className="newsToolbar" aria-label="Filtrer innhold">
        {(["Alle", "Otello", "Bemobi"] as CompanyFilter[]).map((item) => <button className={company === item ? "periodButton active" : "periodButton"} key={item} onClick={() => setCompany(item)} type="button">{item}</button>)}
      </section>
      <section className="newsLayout">
        <div className="newsColumn">
          <div className="sectionHeading"><div><span className="label">SISTE MELDINGER</span><h2>Nyheter</h2></div><span className="pill">{news.length} VIST</span></div>
          {!data && <article className="card emptyNewsCard">Laster meldinger …</article>}
          {data && news.length === 0 && <article className="card emptyNewsCard">Ingen meldinger funnet for dette filteret.</article>}
          <div className="newsList">{news.map((item) => <article className="card newsCard" key={item.id}><div className="newsMeta"><span className={`companyTag company${item.company}`}>{item.company}</span><span>{item.category_label}</span><ImportanceBadge importance={item.importance} /></div><h3>{item.headline}</h3>{item.summary && <p>{item.summary}</p>}<div className="newsCardFooter"><time dateTime={item.published_at ?? undefined}>{dateLabel(item.published_at, true)}</time><SourceLink source={item.source} url={item.url} /></div></article>)}</div>
        </div>
        <aside className="calendarColumn">
          <div className="sectionHeading"><div><span className="label">FREMOVER</span><h2>Hendelseskalender</h2></div></div>
          <div className="card calendarCard">
            {!data && <p className="emptyCalendar">Laster kalender …</p>}
            {data && events.length === 0 && <p className="emptyCalendar">Ingen kjente kommende datoer for dette filteret.</p>}
            {events.map((item) => <div className="calendarEvent" key={item.id}><time dateTime={item.date}><strong>{new Date(`${item.date}T12:00:00Z`).toLocaleDateString("nb-NO", { day: "2-digit" })}</strong><span>{new Date(`${item.date}T12:00:00Z`).toLocaleDateString("nb-NO", { month: "short" })}</span></time><div><div className="newsMeta"><span className={`companyTag company${item.company}`}>{item.company}</span><ImportanceBadge importance={item.importance} /></div><h3>{item.title}</h3><p>{item.date_label} · {item.confirmed ? "Bekreftet" : "Forventet / ikke bekreftet"}</p><SourceLink source={item.source} url={item.url} /></div></div>)}
          </div>
          <p className="calendarNote">Forventede datoer er tydelig merket og kan endres. Kontroller alltid originalkilden.</p>
        </aside>
      </section>
    </div>
  );
}

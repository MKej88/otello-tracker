import { useMemo, useState } from "react";
import { usePollingResource } from "./usePollingResource";
import { formatDate, formatDateTime } from "./uiFormat";
import "./news-events.css";

const REFRESH_MS = 5 * 60 * 1000;
const PAGE_SIZE = 10;
const CALENDAR_LIMIT = 8;

type Importance = "HIGH" | "MEDIUM" | "LOW";
type CompanyFilter = "Alle" | "Otello" | "Bemobi";
type ContentType = "OFFICIAL" | "MEDIA";
type ContentFilter = "Alle" | "Viktige" | "Offisielt" | "Media";
type NavImpact = "DIRECT" | "POTENTIAL" | "NONE";

type NewsItem = {
  id: number;
  company: "Otello" | "Bemobi";
  headline: string;
  published_at?: string | null;
  category?: string | null;
  category_label: string;
  importance: Importance;
  nav_impact?: NavImpact | null;
  summary?: string | null;
  source?: string | null;
  url?: string | null;
  content_type?: ContentType;
  original_language?: string | null;
  paywall_likely?: boolean;
};

type EventItem = {
  id: string;
  date: string;
  company: "Otello" | "Bemobi";
  title: string;
  importance: Importance;
  date_label: string;
  confirmed: boolean;
  source?: string | null;
  url?: string | null;
};

type MediaStatus = {
  available?: boolean;
  status?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  error_count?: number;
};

type Payload = {
  ready: boolean;
  news?: NewsItem[];
  events?: EventItem[];
  media_status?: MediaStatus;
};

const importanceLabels: Record<Importance, string> = {
  HIGH: "Høy",
  MEDIUM: "Middels",
  LOW: "Lav",
};

function dateLabel(input?: string | null, includeTime = false) {
  if (!input) return "Dato mangler";
  return includeTime ? formatDateTime(input) : formatDate(input);
}

function SourceLink({ url, source }: { url?: string | null; source?: string | null }) {
  const label = source ?? "Originalkilde";
  if (!url) return <span className="newsSource">{label}</span>;
  return (
    <a className="newsSourceLink" href={url} target="_blank" rel="noreferrer">
      {label} <span aria-hidden="true">↗</span>
    </a>
  );
}

function NewsSourceMeta({ item }: { item: NewsItem }) {
  return (
    <span className="newsSourceMeta">
      {contentType(item) === "MEDIA" ? "Media" : "Offisiell"} ·{" "}
      {item.paywall_likely && <><span className="paywallBadge">Betalingsmur</span> · </>}
      <SourceLink source={item.source} url={item.url} />
    </span>
  );
}

function ImportanceBadge({ importance }: { importance: Importance }) {
  if (importance === "LOW") return null;
  return <span className={`importanceBadge importance${importance}`}>{importanceLabels[importance]}</span>;
}

function contentType(item: NewsItem): ContentType {
  return item.content_type === "MEDIA" ? "MEDIA" : "OFFICIAL";
}

function categoryLabel(item: NewsItem) {
  return item.category === "JCP" ? "JCP" : item.category_label;
}

function matchesContentFilter(item: NewsItem, filter: ContentFilter) {
  if (filter === "Alle") return true;
  if (filter === "Viktige") {
    return item.importance === "HIGH" || item.nav_impact === "DIRECT" || item.nav_impact === "POTENTIAL";
  }
  return filter === "Media" ? contentType(item) === "MEDIA" : contentType(item) === "OFFICIAL";
}

function importantScore(item: NewsItem) {
  if (item.nav_impact === "DIRECT") return 5;
  if (item.importance === "HIGH") return 4;
  if (item.nav_impact === "POTENTIAL") return 3;
  if (item.importance === "MEDIUM") return 2;
  return 0;
}

function impactLabel(item: NewsItem) {
  if (item.nav_impact === "DIRECT") return "Direkte NAV-effekt";
  if (item.nav_impact === "POTENTIAL") return "Potensiell betydning";
  return null;
}

function translationLabel(item: NewsItem) {
  const language = String(item.original_language ?? "").toLowerCase();
  if (language.startsWith("pt")) {
    return "Automatisk oversatt fra portugisisk · basert på RSS-metadata";
  }
  return "Automatisk oversatt · basert på RSS-metadata";
}

export default function NewsEventsPage() {
  const { data, refreshFailed } = usePollingResource<Payload>(
    "/api/news-events",
    REFRESH_MS,
    true,
  );
  const [company, setCompany] = useState<CompanyFilter>("Alle");
  const [contentFilter, setContentFilter] = useState<ContentFilter>("Alle");
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);

  const filteredNews = useMemo(() => (data?.news ?? []).filter((item) => (
    (company === "Alle" || item.company === company) && matchesContentFilter(item, contentFilter)
  )), [company, contentFilter, data?.news]);

  const importantNews = useMemo(() => filteredNews
    .map((item, index) => ({ item, index, score: importantScore(item) }))
    .filter(({ item }) => (
      item.importance === "HIGH" || item.nav_impact === "DIRECT" || item.nav_impact === "POTENTIAL"
    ))
    .sort((a, b) => b.score - a.score || a.index - b.index)
    .slice(0, 3)
    .map(({ item }) => item), [filteredNews]);

  const importantIds = useMemo(() => new Set(importantNews.map((item) => item.id)), [importantNews]);
  const regularNews = useMemo(() => filteredNews.filter((item) => !importantIds.has(item.id)), [filteredNews, importantIds]);
  const visibleNews = regularNews.slice(0, visibleCount);

  const events = useMemo(() => (data?.events ?? []).filter(
    (item) => company === "Alle" || item.company === company,
  ), [company, data?.events]);
  const calendarEvents = events.slice(0, CALENDAR_LIMIT);

  const nextImportantEvent = useMemo(() => {
    const allEvents = data?.events ?? [];
    return allEvents.find((item) => item.importance === "HIGH") ?? allEvents[0] ?? null;
  }, [data?.events]);

  const mediaStatus = data?.media_status;
  const mediaCheckedAt = mediaStatus?.finished_at ?? mediaStatus?.started_at;
  const mediaDegraded = mediaStatus?.status === "PARTIAL" || mediaStatus?.status === "FAILED";

  function changeCompany(next: CompanyFilter) {
    setCompany(next);
    setVisibleCount(PAGE_SIZE);
  }

  function changeContentFilter(next: ContentFilter) {
    setContentFilter(next);
    setVisibleCount(PAGE_SIZE);
  }

  return (
    <div className="investorPage newsEventsPage">
      <section className="card newsHero newsHeroClean">
        <div>
          <span className="label">NYHETER</span>
          <h2>Siste relevante hendelser for Otello og Bemobi</h2>
          <p>Prioritert etter betydning for caset, med originalkilden ett klikk unna.</p>
          {refreshFailed && <small className="newsStaleNote">Ny oppdatering feilet · viser siste gode data</small>}
        </div>
        <div className="newsNextEvent">
          <span className="label">NESTE VIKTIGE DATO</span>
          {nextImportantEvent ? (
            <>
              <strong>{formatDate(nextImportantEvent.date)}</strong>
              <span>{nextImportantEvent.title}</span>
              <small>{nextImportantEvent.company} · {nextImportantEvent.confirmed ? "Bekreftet" : "Forventet"}</small>
            </>
          ) : (
            <span className="newsNextEventEmpty">Ingen kjent dato</span>
          )}
        </div>
      </section>

      {mediaDegraded && (
        <section className={`card mediaWarning ${mediaStatus?.status === "FAILED" ? "mediaWarningFailed" : "mediaWarningPartial"}`}>
          <div>
            <strong>{mediaStatus?.status === "FAILED" ? "Medieinnhentingen feilet" : "Noen mediekilder feilet"}</strong>
            <span>
              {mediaCheckedAt ? `Siste sjekk ${dateLabel(mediaCheckedAt, true)}. ` : ""}
              {mediaStatus?.error_count ? `${mediaStatus.error_count} feil registrert. ` : ""}
              Dette gjelder mediefeedene; offisielle selskapsmeldinger vises separat.
            </span>
          </div>
        </section>
      )}

      <section className="newsToolbar" aria-label="Filtrer innhold">
        <div className="newsFilterGroup">
          <span className="newsFilterLabel">Selskap</span>
          <div className="newsFilterButtons">
            {(["Alle", "Otello", "Bemobi"] as CompanyFilter[]).map((item) => (
              <button
                className={company === item ? "periodButton active" : "periodButton"}
                key={item}
                onClick={() => changeCompany(item)}
                type="button"
              >
                {item}
              </button>
            ))}
          </div>
        </div>
        <div className="newsFilterGroup">
          <span className="newsFilterLabel">Innhold</span>
          <div className="newsFilterButtons">
            {(["Alle", "Viktige", "Offisielt", "Media"] as ContentFilter[]).map((item) => (
              <button
                className={contentFilter === item ? "periodButton active" : "periodButton"}
                key={item}
                onClick={() => changeContentFilter(item)}
                type="button"
              >
                {item}
              </button>
            ))}
          </div>
        </div>
      </section>

      {importantNews.length > 0 && (
        <section className="importantNewsSection">
          <div className="sectionHeading">
            <div>
              <span className="label">VIKTIGST NÅ</span>
              <h2>Det som kan flytte caset</h2>
            </div>
          </div>
          <div className="importantNewsGrid">
            {importantNews.map((item) => {
              const impact = impactLabel(item);
              return (
                <article className="card importantNewsCard" key={item.id}>
                  <div className="newsCardTop">
                    <div className="newsMeta newsMetaCompact">
                      <span className={`companyTag company${item.company}`}>{item.company}</span>
                      <span>{categoryLabel(item)}</span>
                    </div>
                    <ImportanceBadge importance={item.importance} />
                  </div>
                  <h3>{item.headline}</h3>
                  {item.summary && <p>{item.summary}</p>}
                  {impact && <span className={`impactTag impact${item.nav_impact}`}>{impact}</span>}
                  <div className="newsCardFooter newsCardFooterCompact">
                    <time dateTime={item.published_at ?? undefined}>{dateLabel(item.published_at, true)}</time>
                    <NewsSourceMeta item={item} />
                  </div>
                </article>
              );
            })}
          </div>
        </section>
      )}

      <section className="newsLayout">
        <div className="newsColumn">
          <div className="sectionHeading">
            <div>
              <span className="label">SISTE NYHETER</span>
              <h2>Nyhetsstrøm</h2>
            </div>
            {regularNews.length > 0 && <span className="pill">{Math.min(visibleCount, regularNews.length)} AV {regularNews.length}</span>}
          </div>

          {!data && <article className="card emptyNewsCard">Laster meldinger …</article>}
          {data && filteredNews.length === 0 && <article className="card emptyNewsCard">Ingen meldinger funnet for dette filteret.</article>}
          {data && filteredNews.length > 0 && regularNews.length === 0 && (
            <article className="card emptyNewsCard">Alle treffene for dette filteret vises under «Viktigst nå».</article>
          )}

          <div className="newsList newsListCompact">
            {visibleNews.map((item) => {
              const itemType = contentType(item);
              return (
                <article className="card newsCard newsCardCompact" key={item.id}>
                  <div className="newsCardTop">
                    <div className="newsMeta newsMetaCompact">
                      <span className={`companyTag company${item.company}`}>{item.company}</span>
                      <span>{categoryLabel(item)}</span>
                    </div>
                    <ImportanceBadge importance={item.importance} />
                  </div>
                  <h3>{item.headline}</h3>
                  {item.summary && <p>{item.summary}</p>}
                  {itemType === "MEDIA" && item.original_language && (
                    <span className="translationNote">{translationLabel(item)}</span>
                  )}
                  <div className="newsCardFooter newsCardFooterCompact">
                    <time dateTime={item.published_at ?? undefined}>{dateLabel(item.published_at, true)}</time>
                    <NewsSourceMeta item={item} />
                  </div>
                </article>
              );
            })}
          </div>

          {visibleCount < regularNews.length && (
            <div className="newsLoadMoreWrap">
              <button className="periodButton newsLoadMore" type="button" onClick={() => setVisibleCount((count) => count + PAGE_SIZE)}>
                Vis flere
              </button>
            </div>
          )}
        </div>

        <aside className="calendarColumn">
          <div className="sectionHeading">
            <div>
              <span className="label">FREMOVER</span>
              <h2>Kommende</h2>
            </div>
          </div>
          <div className="card calendarCard calendarCardCompact">
            {!data && <p className="emptyCalendar">Laster kalender …</p>}
            {data && events.length === 0 && <p className="emptyCalendar">Ingen kjente kommende datoer for dette filteret.</p>}
            {calendarEvents.map((item) => (
              <div className="calendarEvent calendarEventCompact" key={item.id}>
                <time dateTime={item.date}><strong>{formatDate(item.date)}</strong></time>
                <div>
                  <div className="newsMeta newsMetaCompact">
                    <span className={`companyTag company${item.company}`}>{item.company}</span>
                    <ImportanceBadge importance={item.importance} />
                  </div>
                  <h3>{item.title}</h3>
                  <p>{item.date_label} · {item.confirmed ? "Bekreftet" : "Forventet"}</p>
                  <SourceLink source={item.source} url={item.url} />
                </div>
              </div>
            ))}
            {events.length > CALENDAR_LIMIT && (
              <p className="calendarMore">+ {events.length - CALENDAR_LIMIT} flere kommende datoer</p>
            )}
          </div>
          <p className="calendarNote">Forventede datoer kan endres. Originalkilden er fasiten.</p>
        </aside>
      </section>
    </div>
  );
}

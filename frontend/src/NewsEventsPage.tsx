import { useMemo, useState } from "react";
import { usePollingResource } from "./usePollingResource";
import { formatDate, formatDateTime } from "./uiFormat";
import "./news-events.css";

const REFRESH_MS = 5 * 60 * 1000;
const PAGE_SIZE = 10;
const CALENDAR_LIMIT = 8;

type Importance = "HIGH" | "MEDIUM" | "LOW";
type Classification = "CONFIRMED_IMPORTANT" | "POSSIBLY_IMPORTANT" | "REVIEW" | "INFORMATION";
type CompanyFilter = "Alle" | "Otello" | "Bemobi";
type ContentFilter = "Alle" | "Viktige";
type NavImpact = "DIRECT" | "POTENTIAL" | "NONE";

type NewsItem = {
  id: number;
  company: "Otello" | "Bemobi";
  headline: string;
  published_at?: string | null;
  category?: string | null;
  category_label: string;
  importance: Importance;
  classification: Classification;
  reason: string;
  case_effect?: string | null;
  nav_impact?: NavImpact | null;
  summary?: string | null;
  source?: string | null;
  url?: string | null;
  original_url?: string | null;
  translation_status?: "PENDING" | "PROCESSING" | "READY" | "FAILED" | "NOT_REQUIRED" | null;
  translated_pdf_url?: string | null;
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

type Payload = {
  ready: boolean;
  news?: NewsItem[];
  events?: EventItem[];
};

const classificationLabels: Record<Classification, string> = {
  CONFIRMED_IMPORTANT: "Bekreftet viktig",
  POSSIBLY_IMPORTANT: "Mulig viktig",
  REVIEW: "Til vurdering",
  INFORMATION: "Informasjon",
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
      {item.translated_pdf_url && <><a className="newsSourceLink" href={item.translated_pdf_url} target="_blank" rel="noreferrer">Les norsk oversettelse ↗</a>{" · "}</>}
      {item.translation_status === "PROCESSING" || item.translation_status === "PENDING" ? <span>Norsk oversettelse behandles … · </span> : null}
      {item.translation_status === "FAILED" ? <span>Norsk oversettelse er foreløpig ikke tilgjengelig. · </span> : null}
      Offisiell · <SourceLink source="Original PDF" url={item.original_url ?? item.url} />
    </span>
  );
}

function ClassificationBadge({ classification }: { classification: Classification }) {
  return <span className={`importanceBadge classification${classification}`}>{classificationLabels[classification]}</span>;
}

function categoryLabel(item: NewsItem) {
  return item.category === "JCP" ? "JCP" : item.category_label;
}

function matchesContentFilter(item: NewsItem, filter: ContentFilter) {
  if (filter === "Alle") return true;
  if (filter === "Viktige") {
    return item.classification === "CONFIRMED_IMPORTANT" || item.classification === "POSSIBLY_IMPORTANT";
  }
  return true;
}

function importantScore(item: NewsItem) {
  if (item.classification === "CONFIRMED_IMPORTANT" && item.nav_impact === "DIRECT") return 3;
  if (item.classification === "CONFIRMED_IMPORTANT") return 2;
  if (item.classification === "POSSIBLY_IMPORTANT") return 1;
  return 0;
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
      item.classification === "CONFIRMED_IMPORTANT" || item.classification === "POSSIBLY_IMPORTANT"
    ))
    .sort((a, b) => b.score - a.score || a.index - b.index)
    .slice(0, 3)
    .map(({ item }) => item), [filteredNews]);

  const regularNews = filteredNews;
  const visibleNews = regularNews.slice(0, visibleCount);

  const events = useMemo(() => (data?.events ?? []).filter(
    (item) => company === "Alle" || item.company === company,
  ), [company, data?.events]);
  const calendarEvents = events.slice(0, CALENDAR_LIMIT);

  const nextImportantEvent = useMemo(() => {
    const allEvents = data?.events ?? [];
    return allEvents.find((item) => item.importance === "HIGH") ?? allEvents[0] ?? null;
  }, [data?.events]);

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
          <p>Kun offisielle meldinger fra NewsWeb, CVM og Bemobis hjemmeside, med originalkilden ett klikk unna.</p>
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
            {(["Alle", "Viktige"] as ContentFilter[]).map((item) => (
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

      <section className="importantNewsSection">
          <div className="sectionHeading">
            <div>
              <span className="label">VIKTIGST NÅ</span>
              <h2>Hendelser som kan påvirke investeringscaset</h2>
            </div>
          </div>
          {!data ? (
            <article className="card emptyNewsCard">Laster analyserte hendelser …</article>
          ) : importantNews.length > 0 ? <div className="importantNewsGrid">
            {importantNews.map((item) => {
              return (
                <article className="card importantNewsCard" key={item.id}>
                  <div className="newsCardTop">
                    <div className="newsMeta newsMetaCompact">
                      <span className={`companyTag company${item.company}`}>{item.company}</span>
                      <span>{categoryLabel(item)}</span>
                    </div>
                    <ClassificationBadge classification={item.classification} />
                  </div>
                  <h3>{item.headline}</h3>
                  {item.case_effect && <strong className="caseEffect">{item.case_effect}</strong>}
                  <p>{item.reason}</p>
                  {item.summary && <><strong className="newsSummaryLabel">Kort fortalt</strong><p>{item.summary}</p></>}
                  <div className="newsCardFooter newsCardFooterCompact">
                    <time dateTime={item.published_at ?? undefined}>{dateLabel(item.published_at, true)}</time>
                    <NewsSourceMeta item={item} />
                  </div>
                </article>
              );
            })}
          </div> : (
            <article className="card importantEmptyState">
              <div><strong>Ingen nye vesentlige hendelser</strong><p>Det er publisert nye regulatoriske dokumenter, men trackeren har ikke identifisert noe som foreløpig endrer investeringscaset.</p></div>
              <a className="periodButton" href="#latest-filings">Se siste filings →</a>
            </article>
          )}
        </section>

      <section className="newsLayout">
        <div className="newsColumn" id="latest-filings">
          <div className="sectionHeading">
            <div>
              <span className="label">SISTE FILINGS</span>
              <h2>Filings og nyheter</h2>
            </div>
            {regularNews.length > 0 && <span className="pill">{Math.min(visibleCount, regularNews.length)} AV {regularNews.length}</span>}
          </div>

          {!data && <article className="card emptyNewsCard">Laster meldinger …</article>}
          {data && filteredNews.length === 0 && <article className="card emptyNewsCard">Ingen meldinger funnet for dette filteret.</article>}
          <div className="newsList newsListCompact">
            {visibleNews.map((item) => {
              return (
                <article className="card newsCard newsCardCompact" key={item.id}>
                  <div className="newsCardTop">
                    <div className="newsMeta newsMetaCompact">
                      <span className={`companyTag company${item.company}`}>{item.company}</span>
                      <span>{categoryLabel(item)}</span>
                    </div>
                    <ClassificationBadge classification={item.classification} />
                  </div>
                  <h3>{item.headline}</h3>
                  {item.summary && <><strong className="newsSummaryLabel">Kort fortalt</strong><p>{item.summary}</p></>}
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
                    <span className={`importanceBadge importance${item.importance}`}>{item.importance === "HIGH" ? "Bekreftet viktig" : item.importance === "MEDIUM" ? "Mulig viktig" : "Informasjon"}</span>
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

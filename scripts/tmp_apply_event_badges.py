from __future__ import annotations

import re
from pathlib import Path


def sub_once(path: str, pattern: str, replacement: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
    if count != 1:
        raise SystemExit(
            f"Expected one regex match in {path}, got {count}: {pattern[:140]!r}"
        )
    target.write_text(updated, encoding="utf-8")


page = "frontend/src/OverviewPage.tsx"

sub_once(
    page,
    r'(type NewsEvent = \{.*?\n  title: string;\n)',
    r'\1  category?: string | null;\n',
)

sub_once(
    page,
    r'''type OverviewEvent = \{
  id: string;
  date: string;
  title: string;
  badge: string;
  badgeClass: "bemobi" \| "otello" \| "macro";
  confirmed: boolean;
  source\?: string \| null;
  importance: number;
  macroExpectation\?: BrazilCalendarExpectation \| null;
\};''',
    '''type OverviewEvent = {
  id: string;
  date: string;
  title: string;
  typeBadge: string;
  scopeBadge: string;
  scopeClass: "bemobi" | "otello" | "brazil";
  eventKind: "company" | "macro";
  confirmed: boolean;
  source?: string | null;
  importance: number;
  macroExpectation?: BrazilCalendarExpectation | null;
};''',
)

sub_once(
    page,
    r'function eventMetaLabel\(event: OverviewEvent\) \{\n  if \(event\.badgeClass === "macro"\) \{',
    'function eventMetaLabel(event: OverviewEvent) {\n  if (event.eventKind === "macro") {',
)

sub_once(
    page,
    r'\nfunction upcomingEvents\(',
    '''
function companyEventType(category?: string | null) {
  const labels: Record<string, string> = {
    RESULTS: "Rapport",
    DIVIDEND: "Utbytte",
    DISTRIBUTION: "Utbytte",
    JCP: "JCP",
    BUYBACK: "Tilbakekjøp",
    M_AND_A: "Transaksjon",
    CAPITAL: "Kapital",
    GUIDANCE: "Utsikter",
  };
  return labels[String(category ?? "").toUpperCase()] ?? "Selskap";
}

function upcomingEvents(''',
)

sub_once(
    page,
    r'''title: event\.title,\n\s*badge: event\.company,\n\s*badgeClass: event\.company === "Bemobi" \? "bemobi" : "otello",\n\s*confirmed: event\.confirmed,''',
    '''title: event.title,
      typeBadge: companyEventType(event.category),
      scopeBadge: event.company,
      scopeClass: event.company === "Bemobi" ? "bemobi" : "otello",
      eventKind: "company",
      confirmed: event.confirmed,''',
)

sub_once(
    page,
    r'''title: macroTitle\(event\),\n\s*badge: "Makro",\n\s*badgeClass: "macro",\n\s*confirmed: true,''',
    '''title: macroTitle(event),
      typeBadge: "Makro",
      scopeBadge: "Brasil",
      scopeClass: "brazil",
      eventKind: "macro",
      confirmed: true,''',
)

sub_once(
    page,
    r'''<div>\n\s*<strong>\{nextEvent\.title\}</strong>\n\s*<span className=\{`overviewEventBadge \$\{nextEvent\.badgeClass\}`\}>\{nextEvent\.badge\}</span>\n\s*</div>''',
    '''<div>
                    <strong>{nextEvent.title}</strong>
                    <span className="overviewEventBadges">
                      <span className="overviewEventBadge type">{nextEvent.typeBadge}</span>
                      <span className={`overviewEventBadge ${nextEvent.scopeClass}`}>{nextEvent.scopeBadge}</span>
                    </span>
                  </div>''',
)

sub_once(
    page,
    r'''<div key=\{event\.id\}>\n\s*<time>\{eventDateLabel\(event\.date\)\}</time>\n\s*<strong>\{event\.title\}</strong>\n\s*<span className=\{`overviewEventBadge \$\{event\.badgeClass\}`\}>\{event\.badge\}</span>\n\s*</div>''',
    '''<div key={event.id}>
                      <time>{eventDateLabel(event.date)}</time>
                      <strong>{event.title}</strong>
                      <span className="overviewEventBadges">
                        <span className="overviewEventBadge type">{event.typeBadge}</span>
                        <span className={`overviewEventBadge ${event.scopeClass}`}>{event.scopeBadge}</span>
                      </span>
                    </div>''',
)

css = "frontend/src/overview-page.css"
target = Path(css)
text = target.read_text(encoding="utf-8")
old = ".overviewEventBadge{font-size:.63rem;font-weight:800;padding:3px 6px;border-radius:999px;background:var(--ot-accent-soft);color:var(--ot-accent-strong)}.overviewEventBadge.otello{background:var(--ot-control-soft);color:var(--ot-text-secondary)}"
new = ".overviewEventBadges{display:inline-flex;align-items:center;gap:5px;flex-wrap:wrap}.overviewEventBadge{font-size:.63rem;font-weight:800;padding:3px 6px;border-radius:999px;background:var(--ot-accent-soft);color:var(--ot-accent-strong)}.overviewEventBadge.type{background:var(--ot-control-soft);color:var(--ot-text-secondary)}.overviewEventBadge.bemobi{background:var(--ot-accent-soft);color:var(--ot-accent-strong)}.overviewEventBadge.otello{background:var(--ot-control-soft);color:var(--ot-text-secondary)}.overviewEventBadge.brazil{background:var(--ot-accent-soft);color:var(--ot-accent-strong)}"
if text.count(old) != 1:
    raise SystemExit("Could not find event badge CSS marker")
text = text.replace(old, new, 1)
old_mobile = ".overviewUpcomingRows .overviewEventBadge{grid-column:2;justify-self:start}"
new_mobile = ".overviewUpcomingRows .overviewEventBadges{grid-column:2;justify-self:start}"
if text.count(old_mobile) != 1:
    raise SystemExit("Could not find mobile event badge CSS marker")
target.write_text(text.replace(old_mobile, new_mobile, 1), encoding="utf-8")

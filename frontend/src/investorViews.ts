export type View =
  | "Oversikt"
  | "NAV"
  | "NAV-sensitivitet"
  | "Historikk"
  | "Tilbakekjøpsprogram"
  | "Bemobi"
  | "Brasil"
  | "Konsensus"
  | "Nyheter"
  | "Datakvalitet";

export const menu: View[] = [
  "Oversikt",
  "NAV",
  "NAV-sensitivitet",
  "Historikk",
  "Tilbakekjøpsprogram",
  "Bemobi",
  "Brasil",
  "Konsensus",
  "Nyheter",
  "Datakvalitet",
];

export const viewSlugs: Record<View, string> = {
  Oversikt: "oversikt",
  NAV: "nav",
  "NAV-sensitivitet": "nav-sensitivitet",
  Historikk: "historikk",
  Tilbakekjøpsprogram: "tilbakekjop",
  Bemobi: "bemobi",
  Brasil: "brasil",
  Konsensus: "konsensus",
  Nyheter: "nyheter",
  Datakvalitet: "datakvalitet",
};

export const viewTitles: Record<View, string> = {
  Oversikt: "Otello investoroversikt",
  NAV: "NAV",
  "NAV-sensitivitet": "NAV-sensitivitet",
  Historikk: "Historisk NAV-rabatt",
  Tilbakekjøpsprogram: "Tilbakekjøpsprogram",
  Bemobi: "Bemobi",
  Brasil: "Brasil",
  Konsensus: "Konsensus",
  Nyheter: "Nyheter og hendelser",
  Datakvalitet: "Datakvalitet",
};

const slugViews = Object.fromEntries(
  Object.entries(viewSlugs).map(([view, slug]) => [slug, view as View]),
) as Record<string, View>;

export function viewFromHash(hash: string): View {
  return slugViews[hash.replace(/^#/, "").toLowerCase()] ?? "Oversikt";
}

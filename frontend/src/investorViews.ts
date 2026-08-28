export type View =
  | "Oversikt"
  | "NAV"
  | "Historikk"
  | "Tilbakekjøpsprogram"
  | "Bemobi"
  | "Konsensus"
  | "Nyheter"
  | "Datakvalitet";

export const menu: View[] = [
  "Oversikt",
  "NAV",
  "Historikk",
  "Tilbakekjøpsprogram",
  "Bemobi",
  "Konsensus",
  "Nyheter",
  "Datakvalitet",
];

export const viewSlugs: Record<View, string> = {
  Oversikt: "oversikt",
  NAV: "nav",
  Historikk: "historikk",
  Tilbakekjøpsprogram: "tilbakekjop",
  Bemobi: "bemobi",
  Konsensus: "konsensus",
  Nyheter: "nyheter",
  Datakvalitet: "datakvalitet",
};

export const viewTitles: Record<View, string> = {
  Oversikt: "Otello investoroversikt",
  NAV: "Estimert NAV",
  Historikk: "Historisk NAV-rabatt",
  Tilbakekjøpsprogram: "Tilbakekjøpsprogram",
  Bemobi: "Bemobi",
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

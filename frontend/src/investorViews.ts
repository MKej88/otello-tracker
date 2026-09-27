export type View =
  | "Oversikt"
  | "NAV"
  | "NAV-sensitivitet"
  | "Historikk"
  | "Tilbakekjøpsprogram"
  | "Cash"
  | "Bemobi"
  | "BRL/NOK"
  | "Brasil"
  | "Konsensus"
  | "Nyheter"
  | "Datakvalitet";

export type NavigationGroup = {
  label: "Verdi" | "Kapital" | "Bemobi" | "Informasjon";
  items: View[];
};

export const navigationGroups: NavigationGroup[] = [
  {
    label: "Verdi",
    items: ["Oversikt", "NAV", "NAV-sensitivitet", "Historikk"],
  },
  {
    label: "Kapital",
    items: ["Tilbakekjøpsprogram", "Cash"],
  },
  {
    label: "Bemobi",
    items: ["Bemobi", "Konsensus", "BRL/NOK", "Brasil"],
  },
  {
    label: "Informasjon",
    items: ["Nyheter", "Datakvalitet"],
  },
];

export const menu: View[] = navigationGroups.flatMap((group) => group.items);

export const viewSlugs: Record<View, string> = {
  Oversikt: "oversikt",
  NAV: "nav",
  "NAV-sensitivitet": "nav-sensitivitet",
  Historikk: "historikk",
  Tilbakekjøpsprogram: "tilbakekjop",
  Cash: "cash",
  Bemobi: "bemobi",
  "BRL/NOK": "brl-nok",
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
  Cash: "Cash & kapitalallokering",
  Bemobi: "Bemobi",
  "BRL/NOK": "BRL/NOK",
  Brasil: "Brasil",
  Konsensus: "Konsensus",
  Nyheter: "Nyheter og hendelser",
  Datakvalitet: "Datakvalitet",
};

export const viewSubtitles: Record<View, string> = {
  Oversikt: "Samlet bilde av verdi, marked og kommende hendelser.",
  NAV: "Beregnet substansverdi og rabatt mot aksjekursen.",
  "NAV-sensitivitet": "Hvordan endrede forutsetninger påvirker estimert NAV.",
  Historikk: "Utviklingen i estimert NAV-rabatt over tid.",
  Tilbakekjøpsprogram: "Fremdrift, volum og kapitalbruk i tilbakekjøpene.",
  Cash: "Kontantbeholdning og disponering av tilgjengelig kapital.",
  Bemobi: "Nøkkeltall og verdiutvikling for Bemobi-investeringen.",
  "BRL/NOK": "Valutautvikling og betydningen for verdier i brasilianske real.",
  Brasil: "Makroøkonomiske forhold som påvirker Brasil-eksponeringen.",
  Konsensus: "Analytikernes forventninger til Bemobis resultater.",
  Nyheter: "Selskapsnyheter og hendelser med mulig investorrelevans.",
  Datakvalitet: "Oppdateringsstatus og kontroller av datagrunnlaget.",
};

const slugViews = Object.fromEntries(
  Object.entries(viewSlugs).map(([view, slug]) => [slug, view as View]),
) as Record<string, View>;

export function viewFromHash(hash: string): View {
  return slugViews[hash.replace(/^#/, "").toLowerCase()] ?? "Oversikt";
}

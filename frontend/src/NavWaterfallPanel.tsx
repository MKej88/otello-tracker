import { useEffect, useMemo, useState } from "react";
import "./nav-waterfall.css";

type WaterfallComponent = {
  key: string;
  label: string;
  amount_mnok: number | null;
  per_share_nok: number | null;
  impact_kind: "TOTAL_AND_PER_SHARE" | "PER_SHARE_ONLY";
  note?: string;
};

type WaterfallBreakdown = {
  label: string;
  perShareNok: number;
  amountMnok?: number | null;
};

type DisplayWaterfallComponent = WaterfallComponent & {
  breakdown?: WaterfallBreakdown[];
};

type WaterfallPoint = {
  full_nav_total_mnok?: number | null;
  full_nav_per_share_nok?: number | null;
  economic_nav_total_mnok?: number | null;
  economic_nav_per_share_nok?: number | null;
  shares_outstanding?: number | null;
  option_overhang_mnok?: number | null;
};

type NavWaterfall = {
  ready: boolean;
  reason?: string;
  quality?: string;
  anchor_date?: string;
  as_of_date?: string;
  anchor?: WaterfallPoint;
  current?: WaterfallPoint;
  change?: {
    economic_nav_total_mnok?: number | null;
    economic_nav_per_share_nok?: number | null;
    shares_outstanding?: number | null;
  };
  components?: WaterfallComponent[];
  reconciliation?: {
    residual_mnok?: number | null;
    per_share_residual_nok?: number | null;
  };
  note?: string;
};

const AUTO_REFRESH_MS = 2 * 60 * 1000;
const UNEXPLAINED_CASH_MNOK_THRESHOLD = 0.5;
const UNEXPLAINED_CASH_PER_SHARE_THRESHOLD = 0.01;

function value(input: number | null | undefined, digits = 2) {
  if (input == null || !Number.isFinite(input)) return "–";
  return input.toLocaleString("nb-NO", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits
  });
}

function signed(input: number | null | undefined, digits = 2, suffix = "") {
  if (input == null || !Number.isFinite(input)) return "–";
  const prefix = input > 0 ? "+" : "";
  return `${prefix}${value(input, digits)}${suffix}`;
}

function dateLabel(input?: string | null) {
  if (!input) return "–";
  const [year, month, day] = input.split("-");
  if (!year || !month || !day) return input;
  return `${day}.${month}.${year}`;
}

function reasonLabel(reason?: string) {
  if (reason === "missing_anchor_full_nav") return "Mangler FULL NAV på siste rapportanker";
  if (reason === "missing_option_values") return "Mangler opsjonsgrunnlag på ett av målepunktene";
  if (reason === "missing_operating_cost_anchor") return "Mangler driftskostnadsanker";
  if (reason === "missing_reported_cash_anchor") return "Mangler rapportert kontantanker";
  if (reason === "api_error") return "Kunne ikke hente waterfall-data";
  return "Waterfall er ikke klar ennå";
}

function isMaterialUnexplainedCash(item: WaterfallComponent) {
  return (
    Math.abs(item.amount_mnok ?? 0) >= UNEXPLAINED_CASH_MNOK_THRESHOLD ||
    Math.abs(item.per_share_nok ?? 0) >= UNEXPLAINED_CASH_PER_SHARE_THRESHOLD
  );
}

function investorComponents(components: WaterfallComponent[]): DisplayWaterfallComponent[] {
  const buybackCash = components.find((item) => item.key === "buyback_cash");
  const shareCount = components.find((item) => item.key === "share_count");
  const canGroupBuybacks = Boolean(buybackCash && shareCount);

  let netBuyback: DisplayWaterfallComponent | null = null;
  if (buybackCash && shareCount) {
    const cashImpact = buybackCash.per_share_nok ?? 0;
    const shareCountImpact = shareCount.per_share_nok ?? 0;
    netBuyback = {
      key: "buyback_net",
      label: "Tilbakekjøp – netto effekt",
      amount_mnok: null,
      per_share_nok: cashImpact + shareCountImpact,
      impact_kind: "PER_SHARE_ONLY",
      note:
        "Netto effekt på NAV per aksje av tilbakekjøp: kontantbruken trekkes fra, mens færre utestående aksjer gir en positiv nevner-effekt når aksjene kjøpes under NAV.",
      breakdown: [
        {
          label: "Kontantbruk",
          perShareNok: cashImpact,
          amountMnok: buybackCash.amount_mnok
        },
        {
          label: "Færre aksjer",
          perShareNok: shareCountImpact,
          amountMnok: null
        }
      ]
    };
  }

  const result: DisplayWaterfallComponent[] = [];
  for (const item of components) {
    if (item.key === "buyback_cash" && netBuyback) {
      result.push(netBuyback);
      continue;
    }
    if (item.key === "share_count" && canGroupBuybacks) continue;

    // Basis-ONA er et rapportanker, ikke en løpende investordriver. Opsjon og
    // Bemobi-fordring vises allerede separat og er derfor de relevante ONA-bevegelsene.
    if (item.key === "ona_ex_option") continue;

    // Kjente kontantstrømmer vises på egne linjer. Residualen er kun en kontrollpost:
    // skjul normal avrundingsstøy, men eksponer et reelt datagap i stedet for å gjemme det.
    if (item.key === "other_cash") {
      if (!isMaterialUnexplainedCash(item)) continue;
      result.push({
        ...item,
        key: "unexplained_cash",
        label: "Uforklart kontantendring",
        note:
          "Kontrollpost for en vesentlig kontantendring som ikke er klassifisert som tilbakekjøp, Bemobi-distribusjon eller annen eksplisitt kontantdriver. Denne bør normalt ikke vises."
      });
      continue;
    }

    result.push(item);
  }
  return result;
}

export default function NavWaterfallPanel() {
  const [data, setData] = useState<NavWaterfall | null>(null);

  useEffect(() => {
    let active = true;
    const load = () => {
      fetch("/api/dashboard/waterfall")
        .then((response) => {
          if (!response.ok) throw new Error("Waterfall API-feil");
          return response.json() as Promise<NavWaterfall>;
        })
        .then((result) => {
          if (active) setData(result);
        })
        .catch(() => {
          if (active) setData({ ready: false, reason: "api_error" });
        });
    };

    load();
    const timer = window.setInterval(load, AUTO_REFRESH_MS);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  const rows = useMemo(() => {
    if (!data?.ready || !data.anchor?.economic_nav_per_share_nok) return [];
    return investorComponents(data.components ?? []);
  }, [data]);

  if (data == null) return null;

  if (!data.ready) {
    return (
      <section className="waterfallPanel waterfallUnavailable">
        <div>
          <span className="waterfallEyebrow">Siden siste rapport</span>
          <strong>{reasonLabel(data.reason)}</strong>
        </div>
      </section>
    );
  }

  const maxImpact = Math.max(
    0.01,
    ...rows.map((item) => Math.abs(item.per_share_nok ?? 0))
  );
  const totalChange = data.change?.economic_nav_per_share_nok;
  const totalTone = totalChange == null || totalChange === 0 ? "neutral" : totalChange > 0 ? "positive" : "negative";
  const reconciled = data.quality === "RECONCILED";

  return (
    <section className="waterfallPanel">
      <div className="waterfallHeader">
        <div>
          <span className="waterfallEyebrow">Siden siste rapport</span>
          <h2>Hva har flyttet økonomisk NAV?</h2>
        </div>
        <span className={reconciled ? "waterfallStatus ok" : "waterfallStatus"}>
          {reconciled ? "AVSTEMT" : "KONTROLLER AVVIK"}
        </span>
      </div>

      <div className="waterfallSummary">
        <div>
          <span>Rapportanker · {dateLabel(data.anchor_date)}</span>
          <strong>{value(data.anchor?.economic_nav_per_share_nok)} kr</strong>
          <small>{value(data.anchor?.economic_nav_total_mnok, 1)} mill. kr</small>
        </div>
        <div className={`waterfallChange ${totalTone}`}>
          <span>Netto endring</span>
          <strong>{signed(totalChange, 2, " kr")}</strong>
          <small>{signed(data.change?.economic_nav_total_mnok, 1, " mill. kr")}</small>
        </div>
        <div>
          <span>I dag · {dateLabel(data.as_of_date)}</span>
          <strong>{value(data.current?.economic_nav_per_share_nok)} kr</strong>
          <small>{value(data.current?.economic_nav_total_mnok, 1)} mill. kr</small>
        </div>
      </div>

      <div className="waterfallRows">
        {rows.map((item) => {
          const impact = item.per_share_nok ?? 0;
          const width = Math.max(2, Math.abs(impact) / maxImpact * 46);
          const positive = impact > 0;
          const negative = impact < 0;
          return (
            <div
              className={`waterfallRow ${item.key === "buyback_net" ? "waterfallRowNetBuyback" : ""}`}
              key={item.key}
              title={item.note}
            >
              <div className="waterfallLabel">
                <strong>{item.label}</strong>
                {item.breakdown ? (
                  <div className="waterfallBreakdown">
                    {item.breakdown.map((detail) => (
                      <span key={detail.label}>
                        {detail.label}: {signed(detail.perShareNok, 2, " kr/aksje")}
                        {detail.amountMnok != null
                          ? ` · ${signed(detail.amountMnok, 1, " mill. kr")}`
                          : ""}
                      </span>
                    ))}
                  </div>
                ) : (
                  <small>
                    {item.amount_mnok == null
                      ? "effekt av endret aksjetall"
                      : `${signed(item.amount_mnok, 1, " mill. kr")}`}
                  </small>
                )}
              </div>
              <div className="waterfallBarTrack" aria-label={`${item.label}: ${signed(impact, 2, " kroner per aksje")}`}>
                <span className="waterfallZero" />
                <span
                  className={`waterfallBar ${positive ? "barPositive" : negative ? "barNegative" : "barNeutral"}`}
                  style={positive
                    ? { left: "50%", width: `${width}%` }
                    : { right: "50%", width: `${width}%` }}
                />
              </div>
              <div className="waterfallImpact">
                <strong className={positive ? "positive" : negative ? "negative" : "neutral"}>
                  {signed(impact, 2, " kr")}
                </strong>
              </div>
            </div>
          );
        })}
      </div>

      <div className="waterfallFooter">
        <span>
          Aksjer: {data.anchor?.shares_outstanding?.toLocaleString("nb-NO") ?? "–"}
          {" → "}
          {data.current?.shares_outstanding?.toLocaleString("nb-NO") ?? "–"}
          {data.change?.shares_outstanding != null
            ? ` (${signed(data.change.shares_outstanding, 0)})`
            : ""}
        </span>
        <span>
          Avstemmingsrest: {value(data.reconciliation?.per_share_residual_nok, 4)} kr/aksje
        </span>
      </div>
    </section>
  );
}
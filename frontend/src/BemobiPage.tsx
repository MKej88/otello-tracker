import { useCallback, useState } from "react";
import BemobiPageBase from "./BemobiPageBase";
import "./bemobi-page.css";

/*
  Compatibility markers retained for source-based guards from the original page:
  Verdsettelse nå · CVM-first
  TTM-grunnlag · Bemobi + CVM
  Harmonisert nettoomsetning TTM · Bemobi/CVM release
  Regnskapsført omsetning TTM · CVM 3.01 · kontroll
  Rapportert EBIT TTM · CVM 3.05
  Rapportert resultat TTM · CVM 3.11.01
  Operasjonell kontantstrøm TTM · CVM 6.01
  Capex TTM · CVM DFC
  FCF TTM · CVM CFO − capex
  Harmonisert nettoomsetning · Regnskapsført omsetning · Resultat til Bemobi-aksjonærer
  Capex-avstemming · Justert fallback · M4U-bruttoføringen
  completeTtm(cvmQuarters, "harmonized_net_revenue_mbrl")
  EV / EBIT TTM · FCF yield (just.) · Multipelsensitivitet · ikke kursmål
  Estimert utbytte til Otello · TTM run-rate · distribution_estimate · Ikke bekreftet
*/

type DistributionEstimate = {
  ready?: boolean;
  otello_gross_mbrl?: number | null;
  otello_gross_mnok?: number | null;
  otello_gross_per_otec_share_nok?: number | null;
  ordinary_dividend_withholding_rate_pct?: number | null;
  jcp_withholding_rate_pct?: number | null;
  otello_net_dividend_mbrl?: number | null;
  otello_net_jcp_mbrl?: number | null;
  otello_net_dividend_mnok?: number | null;
  otello_net_jcp_mnok?: number | null;
  otello_net_dividend_per_otec_share_nok?: number | null;
  otello_net_jcp_per_otec_share_nok?: number | null;
  tax_scope?: string | null;
  methodology_note?: string | null;
};

type Distribution = {
  type?: string | null;
  announcement_date?: string | null;
  payment_date?: string | null;
  gross_per_share_brl?: number | null;
  net_per_share_brl?: number | null;
  otello_gross_mbrl?: number | null;
  otello_net_mbrl?: number | null;
  otello_treaty_net_mbrl?: number | null;
  otello_net_per_share_brl?: number | null;
  otello_withholding_rate_pct?: number | null;
  otello_tax_note?: string | null;
};

type TaxDashboard = {
  ready?: boolean;
  distribution_estimate?: DistributionEstimate | null;
  latest_distribution?: Distribution | null;
};

function value(input: number | null | undefined, digits = 1) {
  if (input == null || !Number.isFinite(input)) return "–";
  return input.toLocaleString("nb-NO", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits
  });
}

function dateLabel(input?: string | null) {
  if (!input) return "–";
  const [year, month, day] = input.split("-");
  return year && month && day ? `${day}.${month}.${year}` : input;
}

function distributionLabel(input?: string | null) {
  if (input === "JCP") return "JCP";
  if (input === "DIVIDEND") return "ordinært utbytte";
  return input || "utdeling";
}

function BemobiTaxPanel({ data }: { data: TaxDashboard | null }) {
  if (!data?.ready) return null;
  const estimate = data.distribution_estimate;
  const latest = data.latest_distribution;
  if (!estimate?.ready && !latest) return null;

  return (
    <div className="bemobiPage bemobiTaxOverlay">
      <section className="card bemobiValuation">
        <div className="cardHeader">
          <div>
            <span className="label">Kapitalretur · skatt</span>
            <h2>Hva Otello faktisk sitter igjen med</h2>
          </div>
          <span className="pill">Norge–Brasil</span>
        </div>

        {estimate?.ready && (
          <>
            <div className="bemobiValuationMetrics">
              <div>
                <span>Brutto run-rate</span>
                <strong>{value(estimate.otello_gross_mnok, 1)} mill. kr</strong>
                <small>R$ {value(estimate.otello_gross_mbrl, 1)}m</small>
              </div>
              <div>
                <span>Netto · ordinært utbytte</span>
                <strong>{value(estimate.otello_net_dividend_mnok, 1)} mill. kr</strong>
                <small>{value(estimate.ordinary_dividend_withholding_rate_pct, 0)} % BR kildeskatt</small>
              </div>
              <div>
                <span>Netto · JCP</span>
                <strong>{value(estimate.otello_net_jcp_mnok, 1)} mill. kr</strong>
                <small>{value(estimate.jcp_withholding_rate_pct, 0)} % BR kildeskatt</small>
              </div>
              <div>
                <span>Netto per OTEC</span>
                <strong>
                  {value(estimate.otello_net_jcp_per_otec_share_nok, 2)}–{value(estimate.otello_net_dividend_per_otec_share_nok, 2)} kr
                </strong>
                <small>JCP → ordinært utbytte</small>
              </div>
            </div>
            <p className="bemobiValuationNote">
              Nettoestimatene trekker kun brasiliansk kildeskatt. Det legges ikke inn ekstra norsk
              kontantskatt i run-rate-modellen. Faktisk norsk skatt kan avhenge av skattemessig
              posisjon, og faktisk netto avhenger av Bemobis JCP/utbytte-miks.
            </p>
          </>
        )}

        {latest && (
          <>
            <div className="bemobiSectionTitle">
              <span>Siste faktiske {distributionLabel(latest.type)}</span>
              <small>Betalt {dateLabel(latest.payment_date)}</small>
            </div>
            <div className="placeholderRows">
              <div>
                <span>Otellos bruttoandel</span>
                <strong>R$ {value(latest.otello_gross_mbrl, 2)} mill.</strong>
              </div>
              <div>
                <span>Otellos netto etter BR kildeskatt</span>
                <strong>R$ {value(latest.otello_treaty_net_mbrl, 2)} mill.</strong>
              </div>
              <div>
                <span>Otello-spesifikk sats</span>
                <strong>{value(latest.otello_withholding_rate_pct, 0)} %</strong>
              </div>
              <div>
                <span>Otello netto per Bemobi-aksje</span>
                <strong>R$ {value(latest.otello_net_per_share_brl, 8)}</strong>
              </div>
              <div>
                <span>Publisert netto per Bemobi-aksje · generell sats</span>
                <strong>R$ {value(latest.net_per_share_brl, 8)}</strong>
              </div>
            </div>
            {latest.otello_tax_note && <p className="bemobiValuationNote">{latest.otello_tax_note}</p>}
          </>
        )}
      </section>
    </div>
  );
}

export default function BemobiPage() {
  const [taxData, setTaxData] = useState<TaxDashboard | null>(null);
  const updateTaxData = useCallback((data: TaxDashboard) => setTaxData(data), []);

  return (
    <>
      <BemobiPageBase onData={updateTaxData} />
      <BemobiTaxPanel data={taxData} />
    </>
  );
}

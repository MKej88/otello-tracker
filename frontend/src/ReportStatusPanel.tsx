import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import "./report-status.css";

type ComponentChange = {
  previous_date?: string | null;
  previous_usd?: number | null;
  current_usd?: number | null;
  delta_usd?: number | null;
};

type ReportStatus = {
  ready: boolean;
  status: string;
  apply_status?: string;
  headline?: string | null;
  published_at?: string | null;
  report_date?: string | null;
  source_period?: string | null;
  parser_version?: string | null;
  source_url?: string | null;
  message?: string | null;
  archive?: {
    pdf_archived?: boolean;
    parsed_archived?: boolean;
  };
  validation?: {
    valid?: boolean;
    issue_count?: number;
    issues?: string[];
  };
  pipeline?: {
    newsweb_processed?: boolean;
    pdf_downloaded?: boolean;
    r2_archived?: boolean;
    parsed?: boolean;
    anchors_applied?: boolean;
    nav_rebuilt?: boolean;
  };
  changes?: {
    cash?: ComponentChange;
    other_net_assets?: ComponentChange;
    option_liability?: ComponentChange;
    recurring_opex?: ComponentChange;
  };
  nav?: {
    rebuilt?: boolean;
    latest_date?: string | null;
    scope?: string | null;
    nav_per_share_nok?: number | null;
    status?: string | null;
  };
  automation?: Record<string, boolean>;
};

const REFRESH_MS = 2 * 60 * 1000;
const integer = new Intl.NumberFormat("nb-NO", { maximumFractionDigits: 0 });

function dateLabel(input?: string | null) {
  if (!input) return "–";
  const value = input.slice(0, 10);
  const [year, month, day] = value.split("-");
  return year && month && day ? `${day}.${month}.${year}` : input;
}

function moneyUsd(input?: number | null) {
  if (input == null || !Number.isFinite(input)) return "–";
  const abs = Math.abs(input);
  if (abs >= 1_000_000) {
    return `USD ${(input / 1_000_000).toLocaleString("nb-NO", { maximumFractionDigits: 2 })}m`;
  }
  return `USD ${integer.format(input)}`;
}

function deltaUsd(input?: number | null) {
  if (input == null || !Number.isFinite(input)) return "–";
  const prefix = input > 0 ? "+" : "";
  const abs = Math.abs(input);
  const formatted = abs >= 1_000_000
    ? `${(input / 1_000_000).toLocaleString("nb-NO", { maximumFractionDigits: 2 })}m`
    : integer.format(input);
  return `${prefix}${formatted}`;
}

function navValue(input?: number | null) {
  if (input == null || !Number.isFinite(input)) return "–";
  return `${input.toLocaleString("nb-NO", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} kr`;
}

function statusText(status?: string | null) {
  switch ((status ?? "").toUpperCase()) {
    case "APPLIED": return "INNLEST";
    case "REVIEW_REQUIRED": return "KREVER KONTROLL";
    case "IGNORED": return "ARKIVERT";
    case "STAGED": return "KLARGJORT";
    case "WAITING": return "VENTER";
    case "PARSED": return "LEST";
    default: return status || "VENTER";
  }
}

function tone(status?: string | null) {
  const normalized = (status ?? "").toUpperCase();
  if (normalized === "APPLIED") return "ok";
  if (normalized === "REVIEW_REQUIRED") return "warn";
  return "wait";
}

function PipelineStep({ label, done, warning = false }: { label: string; done?: boolean; warning?: boolean }) {
  return (
    <div className="reportStep">
      <span className={`reportStepDot ${done ? "done" : warning ? "warning" : ""}`} />
      <span>{label}</span>
      <strong>{done ? "OK" : warning ? "STOPPET" : "VENTER"}</strong>
    </div>
  );
}

function Metric({ label, change }: { label: string; change?: ComponentChange }) {
  return (
    <div className="reportMetric">
      <span>{label}</span>
      <strong>{moneyUsd(change?.current_usd)}</strong>
      <small>
        {change?.previous_usd == null
          ? "Ingen tidligere sammenligning"
          : `${moneyUsd(change.previous_usd)} → ${deltaUsd(change.delta_usd)}`}
      </small>
    </div>
  );
}

function ReportPanel({ report }: { report: ReportStatus | null }) {
  if (!report) {
    return (
      <section className="card reportStatusCard">
        <div className="reportHeader"><div><span className="label">Rapportkontroll</span><h2>Automatisk rapportinnlesing</h2></div><span className="reportStatusPill wait">LASTER</span></div>
      </section>
    );
  }

  if (!report.ready) {
    return (
      <section className="card reportStatusCard">
        <div className="reportHeader">
          <div><span className="label">Rapportkontroll</span><h2>Automatisk rapportinnlesing</h2></div>
          <span className="reportStatusPill wait">{statusText(report.status)}</span>
        </div>
        <p className="reportWaitingText">{report.message ?? "Venter på neste Otello-finansrapport."}</p>
        <div className="reportPipeline compact">
          <PipelineStep label="NewsWeb-overvåkning" done={report.automation?.newsweb_watch} />
          <PipelineStep label="Automatisk PDF-henting" done={report.automation?.pdf_auto_download} />
          <PipelineStep label="R2-arkiv" done={report.automation?.r2_archive} />
          <PipelineStep label="Streng validering" done={report.automation?.strict_validation} />
          <PipelineStep label="NAV-oppdatering" done={report.automation?.nav_rebuild} />
        </div>
      </section>
    );
  }

  const warning = report.status === "REVIEW_REQUIRED" || report.validation?.valid === false;
  const pipeline = report.pipeline ?? {};
  const changes = report.changes ?? {};

  return (
    <section className={`card reportStatusCard ${warning ? "reportNeedsReview" : ""}`}>
      <div className="reportHeader">
        <div>
          <span className="label">Rapportkontroll</span>
          <h2>{report.source_period ? `Otello ${report.source_period}` : "Siste Otello-rapport"}</h2>
          <p>{report.headline ?? "Finansrapport"} · rapportdato {dateLabel(report.report_date)}</p>
        </div>
        <span className={`reportStatusPill ${tone(report.status)}`}>{statusText(report.status)}</span>
      </div>

      <div className="reportPipeline">
        <PipelineStep label="NewsWeb" done={pipeline.newsweb_processed} />
        <PipelineStep label="PDF hentet" done={pipeline.pdf_downloaded} />
        <PipelineStep label="R2 arkivert" done={pipeline.r2_archived} />
        <PipelineStep label="Validering" done={pipeline.parsed} warning={warning} />
        <PipelineStep label="Rapportankre" done={pipeline.anchors_applied} warning={warning} />
        <PipelineStep label="NAV bygget på nytt" done={pipeline.nav_rebuilt} warning={warning && !pipeline.nav_rebuilt} />
      </div>

      {warning && (
        <div className="reportAlert">
          <strong>Eksisterende NAV er beholdt.</strong>
          <span>
            Rapporten er stoppet av fail-closed-kontrollen.
            {report.validation?.issue_count ? ` ${report.validation.issue_count} valideringsavvik er registrert.` : ""}
          </span>
        </div>
      )}

      <div className="reportMetrics">
        <Metric label="Kontantbeholdning" change={changes.cash} />
        <Metric label="Øvrige nettoeiendeler" change={changes.other_net_assets} />
        <Metric label="Opsjonsforpliktelse" change={changes.option_liability} />
        <Metric label="Løpende driftskostnad" change={changes.recurring_opex} />
      </div>

      <div className="reportNavRow">
        <div><span>Full NAV etter rapportbehandling</span><strong>{navValue(report.nav?.nav_per_share_nok)}</strong></div>
        <div><span>NAV-dato</span><strong>{dateLabel(report.nav?.latest_date)}</strong></div>
        <div><span>Parser</span><strong>{report.parser_version ?? "–"}</strong></div>
        {report.source_url && <a href={report.source_url} target="_blank" rel="noreferrer">Åpne kilde-PDF</a>}
      </div>
      <p className="reportFootnote">Endringene over er mot forrige rapporterte anker. De er ikke presentert som et kurs- eller resultatestimat.</p>
    </section>
  );
}

export default function ReportStatusMount() {
  const [target, setTarget] = useState<Element | null>(null);
  const [report, setReport] = useState<ReportStatus | null>(null);

  useEffect(() => {
    setTarget(document.querySelector(".main"));
  }, []);

  useEffect(() => {
    let active = true;
    const load = () => {
      fetch("/api/dashboard/report-status")
        .then((response) => {
          if (!response.ok) throw new Error("Report status API-feil");
          return response.json() as Promise<ReportStatus>;
        })
        .then((data) => { if (active) setReport(data); })
        .catch(() => { if (active) setReport(null); });
    };
    load();
    const timer = window.setInterval(load, REFRESH_MS);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  if (!target) return null;
  return createPortal(<ReportPanel report={report} />, target);
}

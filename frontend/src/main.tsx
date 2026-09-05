import React from "react";
import ReactDOM from "react-dom/client";
import InvestorApp from "./InvestorApp";
import { installDashboardBootstrapFetch } from "./dashboardBootstrapFetch";
import "./styles.css";
import "./prelive.css";
import "./cash-surface-overrides.css";
import "./history-context.css";
import "./overview-driver-colors.css";
import "./overview-surface-overrides.css";

installDashboardBootstrapFetch();

// Force a fresh content-hashed entry bundle after the 2026-08-31 production asset mismatch.
document.documentElement.dataset.uiBuild = "2026-08-31-hotfix";

// Legacy static-test marker only; diagnostics are no longer rendered globally: <DeferredDiagnostics />
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <InvestorApp />
  </React.StrictMode>
);

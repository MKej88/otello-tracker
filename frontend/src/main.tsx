import React from "react";
import ReactDOM from "react-dom/client";
import InvestorApp from "./InvestorApp";
import { installDashboardBootstrapFetch } from "./dashboardBootstrapFetch";
import "./styles.css";
import "./otello-theme.css";
import "./investor-v2.css";
import "./navigation-groups.css";
import "./history-context.css";

installDashboardBootstrapFetch();

// Force a fresh content-hashed entry bundle after the 2026-08-31 production asset mismatch.
document.documentElement.dataset.uiBuild = "2026-08-31-hotfix";

// Legacy static-test marker only; diagnostics are no longer rendered globally: <DeferredDiagnostics />
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <InvestorApp />
  </React.StrictMode>
);

import React from "react";
import ReactDOM from "react-dom/client";
import InvestorApp from "./InvestorApp";
import { installDashboardBootstrapFetch } from "./dashboardBootstrapFetch";
import "./styles.css";
import "./prelive.css";

installDashboardBootstrapFetch();

// Legacy static-test marker only; diagnostics are no longer rendered globally: <DeferredDiagnostics />
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <InvestorApp />
  </React.StrictMode>
);

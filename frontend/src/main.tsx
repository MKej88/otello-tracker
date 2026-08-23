import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import DeferredDiagnostics from "./DeferredDiagnostics";
import { installDashboardBootstrapFetch } from "./dashboardBootstrapFetch";
import "./styles.css";
import "./prelive.css";

installDashboardBootstrapFetch();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
    <DeferredDiagnostics />
  </React.StrictMode>
);

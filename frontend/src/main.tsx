import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import ReportStatusMount from "./ReportStatusPanel";
import "./styles.css";
import "./prelive.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
    <ReportStatusMount />
  </React.StrictMode>
);

import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import EconomicNavPanel from "./EconomicNavPanel";
import "./styles.css";
import "./prelive.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
    <EconomicNavPanel />
  </React.StrictMode>
);

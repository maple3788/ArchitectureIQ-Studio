import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { SharedWorkflowDraftProvider } from "./SharedWorkflowDraft";
import "./styles.css";
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <SharedWorkflowDraftProvider><App /></SharedWorkflowDraftProvider>
  </React.StrictMode>,
);

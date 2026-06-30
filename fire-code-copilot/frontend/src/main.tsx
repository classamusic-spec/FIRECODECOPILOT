import React from "react";
import ReactDOM from "react-dom/client";
import "@fontsource-variable/inter"; // self-hosted Inter (no runtime web-font fetch)
import App from "./App";
import "./index.css";

// Standard Vite + React 18 entry point.
ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);

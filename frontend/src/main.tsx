import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";
import "highlight.js/styles/github-dark.css";
import { getStoredAppSettings } from "./hooks/useSettings";

const BACKEND_READY_TIMEOUT_MS = 6000;
const BACKEND_READY_POLL_INTERVAL_MS = 300;

function sleep(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function buildStartupUrl(path: string): string {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  const configuredBase =
    getStoredAppSettings().apiUrl.trim() || (import.meta.env.VITE_API_URL ?? "").trim();

  if (!configuredBase || configuredBase.startsWith("/")) {
    return normalizedPath;
  }

  if (/^https?:\/\//i.test(configuredBase)) {
    return `${configuredBase.replace(/\/$/, "")}${normalizedPath}`;
  }

  return normalizedPath;
}

async function waitForBackendReady() {
  const healthUrl = buildStartupUrl("/api/health");
  const deadline = Date.now() + BACKEND_READY_TIMEOUT_MS;

  while (Date.now() < deadline) {
    try {
      const response = await fetch(healthUrl, {
        method: "GET",
        credentials: "include",
        cache: "no-store",
      });

      if (response.ok) {
        return;
      }
    } catch {}

    await sleep(BACKEND_READY_POLL_INTERVAL_MS);
  }
}

async function prepare() {
  const shouldUseMock =
    import.meta.env.VITE_USE_MOCK === "true" || getStoredAppSettings().useMock;

  if (shouldUseMock) {
    const { worker } = await import("./mocks/browser");
    await worker.start({ onUnhandledRequest: "bypass" });
    return;
  }

  await waitForBackendReady();
}

prepare().then(() => {
  ReactDOM.createRoot(document.getElementById("app")!).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>
  );
});

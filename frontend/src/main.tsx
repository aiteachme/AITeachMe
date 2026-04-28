import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";
import "highlight.js/styles/github-dark.css";
import "katex/dist/katex.min.css";
import { THEME_STORAGE_KEY, type Theme } from "./components/providers/ThemeProvider";

const BACKEND_READY_TIMEOUT_MS = 6000;
const LOCAL_DESKTOP_BACKEND_READY_TIMEOUT_MS = 60000;
const BACKEND_READY_POLL_INTERVAL_MS = 300;
const BACKEND_READY_REQUEST_TIMEOUT_MS = 1200;
const STARTUP_MESSAGES = {
  startingLocalService: "\u6b63\u5728\u542f\u52a8\u672c\u5730\u670d\u52a1...",
  connectingService: "\u6b63\u5728\u8fde\u63a5\u670d\u52a1...",
  openingInterface: "\u6b63\u5728\u6253\u5f00\u754c\u9762...",
  localServiceSlow: "\u672c\u5730\u670d\u52a1\u9996\u6b21\u542f\u52a8\u8f83\u6162\uff0c\u8bf7\u7a0d\u5019...",
  startingMockData: "\u6b63\u5728\u542f\u52a8\u6a21\u62df\u6570\u636e...",
} as const;

function resolveInitialTheme(theme: Theme): "light" | "dark" {
  if (theme !== "system") {
    return theme;
  }

  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function applyInitialTheme() {
  try {
    const storedTheme = window.localStorage.getItem(THEME_STORAGE_KEY);
    const theme: Theme =
      storedTheme === "light" || storedTheme === "dark" || storedTheme === "system"
        ? storedTheme
        : "system";
    const resolvedTheme = resolveInitialTheme(theme);
    const root = window.document.documentElement;

    root.classList.remove("light", "dark");
    root.classList.add(resolvedTheme);
    root.dataset.themePreference = theme;
    root.style.colorScheme = resolvedTheme;
  } catch {
    // Ignore localStorage access failures and let ThemeProvider recover after mount.
  }
}

function sleep(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function setStartupStatus(message: string) {
  const status = window.document.getElementById("startup-status");
  if (status) {
    status.textContent = message;
  }
}

function resolveConfiguredApiBaseUrl(): string {
  const desktopBase =
    window.location.protocol === "file:"
      ? window.aiteachmeDesktop?.apiBaseUrl ?? "http://127.0.0.1:9020"
      : "";
  return desktopBase || (import.meta.env.VITE_API_URL ?? "").trim();
}

function isLoopbackApiBase(apiBaseUrl: string): boolean {
  return /^https?:\/\/(127\.0\.0\.1|localhost)(:\d+)?/i.test(apiBaseUrl);
}

function isPackagedDesktopShell(): boolean {
  return window.location.protocol === "file:" || window.location.hostname === "tauri.localhost";
}

function getBackendReadyTimeoutMs(apiBaseUrl: string): number {
  if (isPackagedDesktopShell() && isLoopbackApiBase(apiBaseUrl)) {
    return LOCAL_DESKTOP_BACKEND_READY_TIMEOUT_MS;
  }
  return BACKEND_READY_TIMEOUT_MS;
}

function buildStartupUrl(path: string, configuredBase = resolveConfiguredApiBaseUrl()): string {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;

  if (!configuredBase || configuredBase.startsWith("/")) {
    return normalizedPath;
  }

  if (/^https?:\/\//i.test(configuredBase)) {
    return `${configuredBase.replace(/\/$/, "")}${normalizedPath}`;
  }

  return normalizedPath;
}

async function waitForBackendReady() {
  const apiBaseUrl = resolveConfiguredApiBaseUrl();
  const healthUrl = buildStartupUrl("/api/health", apiBaseUrl);
  const timeoutMs = getBackendReadyTimeoutMs(apiBaseUrl);
  const deadline = Date.now() + timeoutMs;
  const localDesktopBackend = isPackagedDesktopShell() && isLoopbackApiBase(apiBaseUrl);

  setStartupStatus(
    localDesktopBackend ? STARTUP_MESSAGES.startingLocalService : STARTUP_MESSAGES.connectingService,
  );

  while (Date.now() < deadline) {
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), BACKEND_READY_REQUEST_TIMEOUT_MS);
    try {
      const response = await fetch(healthUrl, {
        method: "GET",
        credentials: "include",
        cache: "no-store",
        signal: controller.signal,
      });

      if (response.ok) {
        window.clearTimeout(timeoutId);
        setStartupStatus(STARTUP_MESSAGES.openingInterface);
        return;
      }
    } catch {
      // Swallow startup probe failures so the app can still mount and show real UI errors.
    } finally {
      window.clearTimeout(timeoutId);
    }

    if (localDesktopBackend && deadline - Date.now() < timeoutMs - 5000) {
      setStartupStatus(STARTUP_MESSAGES.localServiceSlow);
    }
    await sleep(BACKEND_READY_POLL_INTERVAL_MS);
  }

  setStartupStatus(STARTUP_MESSAGES.openingInterface);
}

async function prepare() {
  const shouldUseMock = window.location.search.includes("mock=1");

  if (shouldUseMock) {
    setStartupStatus(STARTUP_MESSAGES.startingMockData);
    const { worker } = await import("./mocks/browser");
    await worker.start({ onUnhandledRequest: "bypass" });
    return;
  }

  await waitForBackendReady();
}

applyInitialTheme();

prepare()
  .catch(() => {
    // Startup preparation should never block initial rendering.
  })
  .then(() => {
    ReactDOM.createRoot(document.getElementById("app")!).render(
      <React.StrictMode>
        <App />
      </React.StrictMode>,
    );
  });

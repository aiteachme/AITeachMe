import type { CourseShareData } from "../api/generated/model";

function getAppBasePath(): string {
  const base = (import.meta.env.BASE_URL || "").trim();
  if (!base || base === "/" || base === "./") {
    return "";
  }
  return `/${base.replace(/^\/+|\/+$/g, "")}`;
}

function normalizePublicAppBaseUrl(value: string): string {
  const normalized = value.trim();
  if (!normalized) {
    return "";
  }

  try {
    const parsed = new URL(normalized);
    if (!/^https?:$/i.test(parsed.protocol) || parsed.username || parsed.password) {
      return "";
    }
    parsed.search = "";
    parsed.hash = "";
    return parsed.toString().replace(/\/+$/, "");
  } catch {
    return "";
  }
}

function getConfiguredPublicAppBaseUrl(): string {
  if (typeof window === "undefined") {
    return "";
  }

  const runtimeValue = window.__AITEACHME_RUNTIME_CONFIG__?.VITE_PUBLIC_APP_URL;
  const configuredValue = typeof runtimeValue === "string"
    ? runtimeValue
    : import.meta.env.VITE_PUBLIC_APP_URL;
  return normalizePublicAppBaseUrl(configuredValue ?? "");
}

function isDesktopRuntime(): boolean {
  return (
    typeof window !== "undefined" && (
      Boolean(window.electronWindow) ||
      Boolean(window.aiteachmeDesktop) ||
      window.location.protocol === "file:" ||
      window.location.hostname === "tauri.localhost"
    )
  );
}

export function resolveCourseSharePublicBaseUrl(): string {
  const configuredBaseUrl = getConfiguredPublicAppBaseUrl();
  if (configuredBaseUrl) {
    return configuredBaseUrl;
  }
  if (typeof window === "undefined" || isDesktopRuntime() || !/^https?:$/i.test(window.location.protocol)) {
    return "";
  }
  return `${window.location.origin}${getAppBasePath()}`.replace(/\/+$/, "");
}

export function buildCourseShareUrl(share: CourseShareData): string {
  const path = share.share_path || (share.token ? `/share/courses/${share.token}` : "");
  const baseUrl = resolveCourseSharePublicBaseUrl();
  if (!path || !baseUrl) {
    return "";
  }
  return new URL(`${baseUrl}/${path.replace(/^\/+/, "")}`).toString();
}

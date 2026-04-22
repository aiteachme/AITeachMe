import { apiClient } from "../api/client";
import type { SettingsOverviewData } from "../api/generated/model/settingsOverviewData";
import type { ApiResponse } from "../api/types";

const SYSTEM_SETTINGS_STORAGE_KEY = "aiteachme:system-settings-overview";
export const SYSTEM_SETTINGS_CHANGED_EVENT = "aiteachme:system-settings-overview-changed";

let currentOverview: SettingsOverviewData | null = null;
let inFlightOverview: Promise<SettingsOverviewData | null> | null = null;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function normalizeSettingsOverview(raw: unknown): SettingsOverviewData | null {
  if (!isRecord(raw)) {
    return null;
  }

  const settingsSource =
    typeof raw.settings_source === "string" ? raw.settings_source : "";
  const mode = typeof raw.mode === "string" ? raw.mode : "local";
  const sections = Array.isArray(raw.sections) ? (raw.sections as SettingsOverviewData["sections"]) : [];
  const notes = Array.isArray(raw.notes)
    ? raw.notes.filter((item): item is string => typeof item === "string")
    : [];

  return {
    settings_source: settingsSource,
    mode,
    sections,
    notes,
  };
}

export function storeSystemSettingsOverview(overview: SettingsOverviewData | null): void {
  currentOverview = overview;
  if (typeof window === "undefined") {
    return;
  }
  if (!overview) {
    window.localStorage.removeItem(SYSTEM_SETTINGS_STORAGE_KEY);
    window.dispatchEvent(new CustomEvent(SYSTEM_SETTINGS_CHANGED_EVENT, { detail: null }));
    return;
  }
  window.localStorage.setItem(SYSTEM_SETTINGS_STORAGE_KEY, JSON.stringify(overview));
  window.dispatchEvent(new CustomEvent(SYSTEM_SETTINGS_CHANGED_EVENT, { detail: overview }));
}

export function getStoredSystemSettingsOverview(): SettingsOverviewData | null {
  if (currentOverview) {
    return currentOverview;
  }
  if (typeof window === "undefined") {
    return null;
  }

  try {
    const raw = window.localStorage.getItem(SYSTEM_SETTINGS_STORAGE_KEY);
    if (!raw) {
      return null;
    }
    const parsed = normalizeSettingsOverview(JSON.parse(raw));
    currentOverview = parsed;
    return parsed;
  } catch {
    return null;
  }
}

export async function fetchSystemSettingsOverview(): Promise<SettingsOverviewData> {
  const response = await apiClient<ApiResponse<SettingsOverviewData>>({
    url: "/api/v1/system/settings",
    method: "POST",
    data: {},
  });
  const overview = normalizeSettingsOverview(response.data) ?? {
    settings_source: "",
    mode: "local",
    sections: [],
    notes: [],
  };
  storeSystemSettingsOverview(overview);
  return overview;
}

export async function ensureSystemSettingsOverviewLoaded(
  force = false,
): Promise<SettingsOverviewData | null> {
  const cached = getStoredSystemSettingsOverview();
  if (!force && cached) {
    return cached;
  }
  if (inFlightOverview) {
    return inFlightOverview;
  }
  inFlightOverview = fetchSystemSettingsOverview()
    .catch(() => null)
    .finally(() => {
      inFlightOverview = null;
    });
  return inFlightOverview;
}

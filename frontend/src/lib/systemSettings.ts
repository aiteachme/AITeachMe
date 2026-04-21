import { apiClient } from "../api/client";
import type { SettingsOverviewData } from "../api/generated/model/settingsOverviewData";
import type { SettingEntry } from "../api/generated/model/settingEntry";
import type { ApiResponse } from "../api/types";

export type IngestParserProvider = "auto" | "mineru" | "markitdown";
export type IngestMinerUModelVersion = "vlm" | "pipeline";

export interface IngestPreferenceSettings {
  mode: string;
  parserProvider: IngestParserProvider;
  mineruModelVersion: IngestMinerUModelVersion;
  mineruEnableFormula: boolean;
  mineruEnableTable: boolean;
  mineruIsOcr: boolean;
}

const SYSTEM_SETTINGS_STORAGE_KEY = "aiteachme:system-settings-overview";

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
    return;
  }
  window.localStorage.setItem(SYSTEM_SETTINGS_STORAGE_KEY, JSON.stringify(overview));
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

function flattenEntries(overview: SettingsOverviewData | null): SettingEntry[] {
  return overview?.sections?.flatMap((section) => section.entries ?? []) ?? [];
}

function readPrimitiveSetting(
  overview: SettingsOverviewData | null,
  key: string,
): string | number | boolean | null | undefined {
  const entry = flattenEntries(overview).find((item) => item.key === key);
  const candidates = [entry?.value, entry?.default_value];
  for (const candidate of candidates) {
    if (
      candidate === null ||
      typeof candidate === "string" ||
      typeof candidate === "number" ||
      typeof candidate === "boolean"
    ) {
      return candidate;
    }
  }
  return undefined;
}

function normalizeParserProvider(value: unknown): IngestParserProvider {
  if (value === "mineru" || value === "markitdown") {
    return value;
  }
  return "auto";
}

function normalizeMineruModelVersion(value: unknown): IngestMinerUModelVersion {
  if (value === "pipeline") {
    return "pipeline";
  }
  return "vlm";
}

export function getIngestPreferenceSettings(
  overview: SettingsOverviewData | null,
): IngestPreferenceSettings {
  return {
    mode: overview?.mode ?? "local",
    parserProvider: normalizeParserProvider(
      readPrimitiveSetting(overview, "ingest.default_parser_provider"),
    ),
    mineruModelVersion: normalizeMineruModelVersion(
      readPrimitiveSetting(overview, "ingest.mineru_model_version"),
    ),
    mineruEnableFormula:
      readPrimitiveSetting(overview, "ingest.mineru_enable_formula") !== false,
    mineruEnableTable:
      readPrimitiveSetting(overview, "ingest.mineru_enable_table") !== false,
    mineruIsOcr:
      readPrimitiveSetting(overview, "ingest.mineru_is_ocr") === true,
  };
}

export async function loadIngestPreferenceSettings(): Promise<IngestPreferenceSettings> {
  const overview = await ensureSystemSettingsOverviewLoaded();
  return getIngestPreferenceSettings(overview);
}

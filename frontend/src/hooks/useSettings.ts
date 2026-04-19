import { useCallback, useSyncExternalStore } from "react";

export type ParserProvider = "docling" | "unstructured" | "mineru";
export type MinerUModelVersion = "vlm" | "pipeline";

export interface AppSettings {
  apiUrl: string;
  useMock: boolean;
  /** `.env.sample` 风格的本机环境变量，仅存当前浏览器 localStorage。 */
  localEnv: Record<string, string>;
  parserProvider: ParserProvider;
  /** MinerU: 个人 API Token（仅存前端 localStorage，上传时随请求传给后端）。 */
  mineruApiToken: string;
  /** MinerU: 是否开启公式识别。 */
  mineruEnableFormula: boolean;
  /** MinerU: 是否开启表格识别。 */
  mineruEnableTable: boolean;
  /** MinerU: 是否开启 OCR（通常用于图片型文档/扫描件）。 */
  mineruIsOcr: boolean;
  /** MinerU: 模型版本（对应请求中的 model_version）。 */
  mineruModelVersion: MinerUModelVersion;
  debugMode: boolean;
}

export const APP_SETTINGS_STORAGE_KEY = "app-settings";

export const DEFAULT_SETTINGS: AppSettings = {
  apiUrl: import.meta.env.VITE_API_URL || "http://localhost:8000",
  useMock: import.meta.env.VITE_USE_MOCK === "true",
  localEnv: {},
  parserProvider: "docling",
  mineruApiToken: "",
  mineruEnableFormula: true,
  mineruEnableTable: true,
  mineruIsOcr: false,
  mineruModelVersion: "vlm",
  debugMode: false,
};

const SETTINGS_CHANGE_EVENT = "aiteachme:settings-change";
const listeners = new Set<() => void>();

let currentSettings: AppSettings = { ...DEFAULT_SETTINGS };
let hasLoadedInitialSettings = false;
let hasBoundStorageListener = false;

function normalizeParserProvider(value: unknown): ParserProvider {
  if (value === "unstructured") {
    return "unstructured";
  }
  if (value === "mineru") {
    return "mineru";
  }
  return "docling";
}

function normalizeMinerUModelVersion(value: unknown): MinerUModelVersion {
  if (value === "pipeline") {
    return "pipeline";
  }
  return "vlm";
}

function normalizeSettings(settings: Partial<AppSettings>): AppSettings {
  const merged = { ...DEFAULT_SETTINGS, ...settings };
  const localEnv =
    typeof merged.localEnv === "object" && merged.localEnv !== null
      ? Object.fromEntries(
          Object.entries(merged.localEnv).map(([key, value]) => [key, String(value ?? "")]),
        )
      : {};
  if (!localEnv.VITE_API_URL && merged.apiUrl) {
    localEnv.VITE_API_URL = String(merged.apiUrl);
  }
  if (!localEnv.VITE_USE_MOCK) {
    localEnv.VITE_USE_MOCK = String(Boolean(merged.useMock));
  }
  if (!localEnv.MINERU_API_TOKEN && merged.mineruApiToken) {
    localEnv.MINERU_API_TOKEN = String(merged.mineruApiToken);
  }
  return {
    apiUrl: String(localEnv.VITE_API_URL || merged.apiUrl || DEFAULT_SETTINGS.apiUrl),
    useMock: localEnv.VITE_USE_MOCK
      ? localEnv.VITE_USE_MOCK.trim().toLowerCase() === "true"
      : typeof merged.useMock === "boolean" ? merged.useMock : DEFAULT_SETTINGS.useMock,
    localEnv,
    parserProvider: normalizeParserProvider(merged.parserProvider),
    mineruApiToken: String(localEnv.MINERU_API_TOKEN ?? merged.mineruApiToken ?? DEFAULT_SETTINGS.mineruApiToken),
    mineruEnableFormula:
      typeof merged.mineruEnableFormula === "boolean"
        ? merged.mineruEnableFormula
        : DEFAULT_SETTINGS.mineruEnableFormula,
    mineruEnableTable:
      typeof merged.mineruEnableTable === "boolean"
        ? merged.mineruEnableTable
        : DEFAULT_SETTINGS.mineruEnableTable,
    mineruIsOcr:
      typeof merged.mineruIsOcr === "boolean" ? merged.mineruIsOcr : DEFAULT_SETTINGS.mineruIsOcr,
    mineruModelVersion: normalizeMinerUModelVersion(merged.mineruModelVersion),
    debugMode:
      typeof merged.debugMode === "boolean" ? merged.debugMode : DEFAULT_SETTINGS.debugMode,
  };
}

function readSettingsFromStorage(): AppSettings {
  if (typeof window === "undefined") {
    return currentSettings;
  }

  try {
    const stored = window.localStorage.getItem(APP_SETTINGS_STORAGE_KEY);
    if (!stored) {
      return { ...DEFAULT_SETTINGS };
    }

    return normalizeSettings(JSON.parse(stored) as Partial<AppSettings>);
  } catch (error) {
    console.warn("Failed to parse app settings from localStorage", error);
    return { ...DEFAULT_SETTINGS };
  }
}

function notifyListeners() {
  listeners.forEach((listener) => listener());
}

function emitSettingsChanged() {
  notifyListeners();

  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent(SETTINGS_CHANGE_EVENT, { detail: currentSettings }));
  }
}

function syncSettingsFromStorage() {
  currentSettings = readSettingsFromStorage();
  hasLoadedInitialSettings = true;
}

function handleStorageChange(event: StorageEvent) {
  if (event.key !== null && event.key !== APP_SETTINGS_STORAGE_KEY) {
    return;
  }

  syncSettingsFromStorage();
  notifyListeners();
}

function ensureStoreInitialized() {
  if (typeof window === "undefined") {
    return;
  }

  if (!hasLoadedInitialSettings) {
    syncSettingsFromStorage();
  }

  if (!hasBoundStorageListener) {
    window.addEventListener("storage", handleStorageChange);
    hasBoundStorageListener = true;
  }
}

function writeSettings(nextSettings: AppSettings) {
  currentSettings = normalizeSettings(nextSettings);
  hasLoadedInitialSettings = true;

  if (typeof window !== "undefined") {
    window.localStorage.setItem(APP_SETTINGS_STORAGE_KEY, JSON.stringify(currentSettings));
  }

  emitSettingsChanged();
}

export function getStoredAppSettings(): AppSettings {
  ensureStoreInitialized();
  return currentSettings;
}

export function useSettings() {
  const settings = useSyncExternalStore(
    (listener) => {
      ensureStoreInitialized();
      listeners.add(listener);

      return () => {
        listeners.delete(listener);
      };
    },
    getStoredAppSettings,
    () => DEFAULT_SETTINGS,
  );

  const updateSettings = useCallback((newSettings: Partial<AppSettings>) => {
    const nextSettings = {
      ...getStoredAppSettings(),
      ...newSettings,
    };
    writeSettings(normalizeSettings(nextSettings));
  }, []);

  const resetSettings = useCallback(() => {
    currentSettings = { ...DEFAULT_SETTINGS };
    hasLoadedInitialSettings = true;

    if (typeof window !== "undefined") {
      window.localStorage.removeItem(APP_SETTINGS_STORAGE_KEY);
    }

    emitSettingsChanged();
  }, []);

  return { settings, updateSettings, resetSettings };
}

export { SETTINGS_CHANGE_EVENT };

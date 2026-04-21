import { useCallback, useSyncExternalStore } from "react";

export interface AppSettings {
  apiUrl: string;
  useMock: boolean;
  /** MinerU: 个人 API Token（仅存前端 localStorage，上传时随请求传给后端）。 */
  mineruApiToken: string;
  debugMode: boolean;
}

export const APP_SETTINGS_STORAGE_KEY = "app-settings";

export const DEFAULT_SETTINGS: AppSettings = {
  apiUrl: import.meta.env.VITE_API_URL || "http://localhost:8000",
  useMock: import.meta.env.VITE_USE_MOCK === "true",
  mineruApiToken: "",
  debugMode: false,
};

const SETTINGS_CHANGE_EVENT = "aiteachme:settings-change";
const listeners = new Set<() => void>();

let currentSettings: AppSettings = { ...DEFAULT_SETTINGS };
let hasLoadedInitialSettings = false;
let hasBoundStorageListener = false;

function normalizeSettings(settings: Partial<AppSettings>): AppSettings {
  const merged = { ...DEFAULT_SETTINGS, ...settings };
  const legacyLocalEnv =
    typeof (settings as { localEnv?: unknown }).localEnv === "object" &&
    (settings as { localEnv?: unknown }).localEnv !== null
      ? Object.fromEntries(
          Object.entries((settings as { localEnv?: Record<string, unknown> }).localEnv ?? {}).map(([key, value]) => [key, String(value ?? "")]),
        )
      : {};
  return {
    apiUrl: String(legacyLocalEnv.VITE_API_URL || merged.apiUrl || DEFAULT_SETTINGS.apiUrl),
    useMock: legacyLocalEnv.VITE_USE_MOCK
      ? legacyLocalEnv.VITE_USE_MOCK.trim().toLowerCase() === "true"
      : typeof merged.useMock === "boolean" ? merged.useMock : DEFAULT_SETTINGS.useMock,
    mineruApiToken: String(legacyLocalEnv.MINERU_API_TOKEN ?? merged.mineruApiToken ?? DEFAULT_SETTINGS.mineruApiToken),
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

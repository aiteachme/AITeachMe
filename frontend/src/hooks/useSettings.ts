import { useCallback, useSyncExternalStore } from "react";

export type ParserProvider = "docling" | "unstructured" | "mineru" | "markitdown";
export type ParserMode = "balanced" | "quality" | "speed";
export type OcrProvider = "none" | "tesseract" | "azure-document-intelligence";
export type MinerUModelVersion = "vlm" | "pipeline";

export interface AppSettings {
  apiUrl: string;
  useMock: boolean;
  providerBaseUrl: string;
  providerApiKey: string;
  modelProvider: string;
  primaryModel: string;
  reasoningModel: string;
  embeddingModel: string;
  fallbackModel: string;
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
  parserMode: ParserMode;
  ocrProvider: OcrProvider;
  parserChunkSize: number;
  parserChunkOverlap: number;
  parserTableExtraction: boolean;
  retrievalTopK: number;
  retrievalScoreThreshold: number;
  enableWebSearch: boolean;
  enableRerank: boolean;
  generationTemperature: number;
  generationTopP: number;
  generationPresencePenalty: number;
  generationFrequencyPenalty: number;
  generationMaxTokens: number;
  generationSeed: number;
  generationStream: boolean;
  runtimeRequestTimeoutMs: number;
  runtimeMaxConcurrency: number;
  autoSaveSettings: boolean;
  debugMode: boolean;
}

export const APP_SETTINGS_STORAGE_KEY = "app-settings";

export const DEFAULT_SETTINGS: AppSettings = {
  apiUrl: import.meta.env.VITE_API_URL || "http://localhost:8000",
  useMock: import.meta.env.VITE_USE_MOCK === "true",
  providerBaseUrl: "",
  providerApiKey: "",
  modelProvider: "openai-compatible",
  primaryModel: "gpt-4.1-mini",
  reasoningModel: "gpt-4.1",
  embeddingModel: "text-embedding-3-large",
  fallbackModel: "gpt-4.1-mini",
  parserProvider: "docling",
  mineruApiToken: "",
  mineruEnableFormula: true,
  mineruEnableTable: true,
  mineruIsOcr: false,
  mineruModelVersion: "vlm",
  parserMode: "balanced",
  ocrProvider: "none",
  parserChunkSize: 1200,
  parserChunkOverlap: 180,
  parserTableExtraction: true,
  retrievalTopK: 8,
  retrievalScoreThreshold: 0.2,
  enableWebSearch: false,
  enableRerank: true,
  generationTemperature: 0.35,
  generationTopP: 0.95,
  generationPresencePenalty: 0,
  generationFrequencyPenalty: 0,
  generationMaxTokens: 4096,
  generationSeed: 0,
  generationStream: true,
  runtimeRequestTimeoutMs: 10000,
  runtimeMaxConcurrency: 4,
  autoSaveSettings: false,
  debugMode: false,
};

const SETTINGS_CHANGE_EVENT = "aiteachme:settings-change";
const listeners = new Set<() => void>();

let currentSettings: AppSettings = { ...DEFAULT_SETTINGS };
let hasLoadedInitialSettings = false;
let hasBoundStorageListener = false;

function clampNumber(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) {
    return min;
  }
  if (value < min) {
    return min;
  }
  if (value > max) {
    return max;
  }
  return value;
}

function normalizeParserProvider(value: unknown): ParserProvider {
  if (value === "unstructured") {
    return "unstructured";
  }
  if (value === "mineru") {
    return "mineru";
  }
  if (value === "markitdown") {
    return "markitdown";
  }
  return "docling";
}

function normalizeParserMode(value: unknown): ParserMode {
  if (value === "quality") {
    return "quality";
  }
  if (value === "speed") {
    return "speed";
  }
  return "balanced";
}

function normalizeOcrProvider(value: unknown): OcrProvider {
  if (value === "tesseract") {
    return "tesseract";
  }
  if (value === "azure-document-intelligence") {
    return "azure-document-intelligence";
  }
  return "none";
}

function normalizeMinerUModelVersion(value: unknown): MinerUModelVersion {
  if (value === "pipeline") {
    return "pipeline";
  }
  return "vlm";
}

function normalizeSettings(settings: Partial<AppSettings>): AppSettings {
  const merged = { ...DEFAULT_SETTINGS, ...settings };
  return {
    apiUrl: String(merged.apiUrl ?? DEFAULT_SETTINGS.apiUrl),
    useMock: typeof merged.useMock === "boolean" ? merged.useMock : DEFAULT_SETTINGS.useMock,
    providerBaseUrl: String(merged.providerBaseUrl ?? DEFAULT_SETTINGS.providerBaseUrl),
    providerApiKey: String(merged.providerApiKey ?? DEFAULT_SETTINGS.providerApiKey),
    modelProvider: String(merged.modelProvider ?? DEFAULT_SETTINGS.modelProvider),
    primaryModel: String(merged.primaryModel ?? DEFAULT_SETTINGS.primaryModel),
    reasoningModel: String(merged.reasoningModel ?? DEFAULT_SETTINGS.reasoningModel),
    embeddingModel: String(merged.embeddingModel ?? DEFAULT_SETTINGS.embeddingModel),
    fallbackModel: String(merged.fallbackModel ?? DEFAULT_SETTINGS.fallbackModel),
    parserProvider: normalizeParserProvider(merged.parserProvider),
    mineruApiToken: String(merged.mineruApiToken ?? DEFAULT_SETTINGS.mineruApiToken),
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
    parserMode: normalizeParserMode(merged.parserMode),
    ocrProvider: normalizeOcrProvider(merged.ocrProvider),
    parserChunkSize: Math.round(clampNumber(Number(merged.parserChunkSize), 256, 4096)),
    parserChunkOverlap: Math.round(clampNumber(Number(merged.parserChunkOverlap), 0, 1024)),
    parserTableExtraction:
      typeof merged.parserTableExtraction === "boolean"
        ? merged.parserTableExtraction
        : DEFAULT_SETTINGS.parserTableExtraction,
    retrievalTopK: Math.round(clampNumber(Number(merged.retrievalTopK), 1, 30)),
    retrievalScoreThreshold: clampNumber(Number(merged.retrievalScoreThreshold), 0, 1),
    enableWebSearch:
      typeof merged.enableWebSearch === "boolean"
        ? merged.enableWebSearch
        : DEFAULT_SETTINGS.enableWebSearch,
    enableRerank:
      typeof merged.enableRerank === "boolean"
        ? merged.enableRerank
        : DEFAULT_SETTINGS.enableRerank,
    generationTemperature: clampNumber(
      Number(merged.generationTemperature),
      0,
      2,
    ),
    generationTopP: clampNumber(Number(merged.generationTopP), 0, 1),
    generationPresencePenalty: clampNumber(Number(merged.generationPresencePenalty), -2, 2),
    generationFrequencyPenalty: clampNumber(Number(merged.generationFrequencyPenalty), -2, 2),
    generationMaxTokens: Math.round(clampNumber(Number(merged.generationMaxTokens), 256, 32768)),
    generationSeed: Math.round(clampNumber(Number(merged.generationSeed), 0, 999999999)),
    generationStream:
      typeof merged.generationStream === "boolean"
        ? merged.generationStream
        : DEFAULT_SETTINGS.generationStream,
    runtimeRequestTimeoutMs: Math.round(
      clampNumber(Number(merged.runtimeRequestTimeoutMs), 3000, 120000),
    ),
    runtimeMaxConcurrency: Math.round(
      clampNumber(Number(merged.runtimeMaxConcurrency), 1, 16),
    ),
    autoSaveSettings:
      typeof merged.autoSaveSettings === "boolean"
        ? merged.autoSaveSettings
        : DEFAULT_SETTINGS.autoSaveSettings,
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

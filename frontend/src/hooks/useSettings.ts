import { useState, useCallback } from "react";

export interface AppSettings {
  apiUrl: string;
  useMock: boolean;
  providerBaseUrl: string;
  providerApiKey: string;
}

const DEFAULT_SETTINGS: AppSettings = {
  apiUrl: import.meta.env.VITE_API_URL || "http://localhost:8000",
  useMock: import.meta.env.VITE_USE_MOCK === "true",
  providerBaseUrl: "",
  providerApiKey: "",
};

export function useSettings() {
  const [settings, setSettingsState] = useState<AppSettings>(() => {
    try {
      const stored = localStorage.getItem("app-settings");
      if (stored) {
        return { ...DEFAULT_SETTINGS, ...JSON.parse(stored) };
      }
    } catch (e) {
      console.warn("Failed to parse app settings from localStorage", e);
    }
    return DEFAULT_SETTINGS;
  });

  const updateSettings = useCallback((newSettings: Partial<AppSettings>) => {
    setSettingsState((prev) => {
      const updated = { ...prev, ...newSettings };
      localStorage.setItem("app-settings", JSON.stringify(updated));
      return updated;
    });
  }, []);

  const resetSettings = useCallback(() => {
    localStorage.removeItem("app-settings");
    setSettingsState(DEFAULT_SETTINGS);
  }, []);

  return { settings, updateSettings, resetSettings };
}

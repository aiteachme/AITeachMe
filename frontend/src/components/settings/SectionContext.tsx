import { createContext, useContext, type ReactNode } from "react";

import type { AppSettings } from "../../hooks/useSettings";

import type { DraftRecord, SettingPrimitive, SettingSection } from "./types";

export interface SectionContextValue {
  isLocalRuntime: boolean;
  sectionMap: Record<string, SettingSection>;
  isOverviewLoading: boolean;
  overviewError: string | null;

  // Server-persisted settings overrides.
  settingsDraft: DraftRecord;
  defaultSettingsDraft: DraftRecord;
  patchServerSetting: (key: string, value: SettingPrimitive) => void;

  // Local .env overrides (local mode only).
  envDraft: DraftRecord;
  patchEnvSetting: (key: string, value: SettingPrimitive) => void;

  // Browser-local preferences.
  draft: AppSettings;
  patchAppSetting: <K extends keyof AppSettings>(key: K, value: AppSettings[K]) => void;
}

const SectionContext = createContext<SectionContextValue | null>(null);

export function SectionContextProvider({
  value,
  children,
}: {
  value: SectionContextValue;
  children: ReactNode;
}) {
  return <SectionContext.Provider value={value}>{children}</SectionContext.Provider>;
}

export function useSectionContext(): SectionContextValue {
  const ctx = useContext(SectionContext);
  if (!ctx) {
    throw new Error("useSectionContext must be used inside SectionContextProvider");
  }
  return ctx;
}

export function useSectionEntries(...ids: string[]) {
  const { sectionMap } = useSectionContext();
  return ids.flatMap((id) => sectionMap[id]?.entries ?? []);
}

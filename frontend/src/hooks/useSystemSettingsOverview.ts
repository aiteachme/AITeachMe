import { useEffect, useSyncExternalStore } from "react";

import type { SettingsOverviewData } from "../api/generated/model/settingsOverviewData";
import {
  ensureSystemSettingsOverviewLoaded,
  getStoredSystemSettingsOverview,
  subscribeSystemSettingsOverview,
} from "../lib/systemSettings";

export function useSystemSettingsOverview(): SettingsOverviewData | null {
  const overview = useSyncExternalStore(
    subscribeSystemSettingsOverview,
    getStoredSystemSettingsOverview,
    () => null,
  );

  useEffect(() => {
    if (!overview) {
      void ensureSystemSettingsOverviewLoaded();
    }
  }, [overview]);

  return overview;
}

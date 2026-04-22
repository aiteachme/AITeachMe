import { useCallback, useEffect, useMemo, useState } from "react";

import { apiClient, getApiErrorMessage } from "../../api/client";
import {
  getStoredSystemSettingsOverview,
  storeSystemSettingsOverview,
} from "../../lib/systemSettings";

import {
  buildChangedFlatPayload,
  buildChangedSettingsPayload,
  draftFromEntries,
  editableEntries,
  sameDraft,
} from "./helpers";
import type {
  ApiEnvelope,
  DraftRecord,
  SaveState,
  SettingEntry,
  SettingSection,
  SettingsOverviewData,
} from "./types";

function collectEditableServerEntries(sections: SettingSection[]): SettingEntry[] {
  return editableEntries(sections, "settings").concat(
    editableEntries(sections, "system_settings"),
  );
}

function collectEditableEnvEntries(sections: SettingSection[]): SettingEntry[] {
  return editableEntries(sections, "env");
}

interface UseSettingsOverviewOptions {
  isOpen: boolean;
}

export function useSettingsOverview({ isOpen }: UseSettingsOverviewOptions) {
  const [overview, setOverview] = useState<SettingsOverviewData | null>(
    () => getStoredSystemSettingsOverview(),
  );
  const [isOverviewLoading, setIsOverviewLoading] = useState(false);
  const [overviewError, setOverviewError] = useState<string | null>(null);

  const [settingsDraft, setSettingsDraft] = useState<DraftRecord>({});
  const [savedSettingsDraft, setSavedSettingsDraft] = useState<DraftRecord>({});
  const [defaultSettingsDraft, setDefaultSettingsDraft] = useState<DraftRecord>({});
  const [envDraft, setEnvDraft] = useState<DraftRecord>({});
  const [savedEnvDraft, setSavedEnvDraft] = useState<DraftRecord>({});
  const [defaultEnvDraft, setDefaultEnvDraft] = useState<DraftRecord>({});

  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [saveError, setSaveError] = useState<string | null>(null);

  const applyOverview = useCallback((next: SettingsOverviewData) => {
    const sections = next.sections ?? [];
    const serverEntries = collectEditableServerEntries(sections);
    const envEntries = collectEditableEnvEntries(sections);
    const nextSettingsDraft = draftFromEntries(serverEntries);
    const nextEnvDraft = draftFromEntries(envEntries);
    setOverview(next);
    storeSystemSettingsOverview(next);
    setSettingsDraft(nextSettingsDraft);
    setSavedSettingsDraft(nextSettingsDraft);
    setDefaultSettingsDraft(draftFromEntries(serverEntries, "default_value"));
    setEnvDraft(nextEnvDraft);
    setSavedEnvDraft(nextEnvDraft);
    setDefaultEnvDraft(draftFromEntries(envEntries, "default_value"));
  }, []);

  useEffect(() => {
    if (!isOpen) return;
    let cancelled = false;

    async function loadOverview() {
      setIsOverviewLoading(true);
      setOverviewError(null);
      try {
        const response = await apiClient<ApiEnvelope<SettingsOverviewData>>({
          url: "/api/v1/system/settings",
          method: "POST",
          data: {},
        });
        if (cancelled) return;
        applyOverview(response.data);
      } catch (error) {
        if (!cancelled) {
          setOverviewError(
            getApiErrorMessage(error, "读取后端设置失败，请确认后端服务可用。"),
          );
        }
      } finally {
        if (!cancelled) setIsOverviewLoading(false);
      }
    }

    void loadOverview();
    return () => {
      cancelled = true;
    };
  }, [isOpen, applyOverview]);

  useEffect(() => {
    if (!isOpen) {
      setSaveState("idle");
      setSaveError(null);
      setOverviewError(null);
    }
  }, [isOpen]);

  const editableServerEntries = useMemo(
    () => collectEditableServerEntries(overview?.sections ?? []),
    [overview],
  );

  const hasServerChanges = useMemo(
    () => !sameDraft(settingsDraft, savedSettingsDraft),
    [savedSettingsDraft, settingsDraft],
  );
  const hasEnvChanges = useMemo(
    () => !sameDraft(envDraft, savedEnvDraft),
    [envDraft, savedEnvDraft],
  );

  const patchServerSetting = useCallback(
    (key: string, value: DraftRecord[string]) => {
      setSettingsDraft((prev) => (
        prev[key] === value ? prev : { ...prev, [key]: value }
      ));
    },
    [],
  );

  const patchEnvSetting = useCallback(
    (key: string, value: DraftRecord[string]) => {
      setEnvDraft((prev) => (
        prev[key] === value ? prev : { ...prev, [key]: value }
      ));
    },
    [],
  );

  const resetServerDrafts = useCallback(() => {
    setSettingsDraft(defaultSettingsDraft);
    setEnvDraft(defaultEnvDraft);
    setSaveError(null);
  }, [defaultSettingsDraft, defaultEnvDraft]);

  const saveAll = useCallback(async () => {
    if (!hasServerChanges && !hasEnvChanges) {
      setSaveState("saved");
      window.setTimeout(() => setSaveState("idle"), 1400);
      return;
    }

    setSaveState("saving");
    setSaveError(null);
    try {
      const reset = sameDraft(settingsDraft, defaultSettingsDraft);
      const response = await apiClient<ApiEnvelope<SettingsOverviewData>>({
        url: "/api/v1/system/settings",
        method: "PATCH",
        data: {
          settings: reset
            ? {}
            : buildChangedSettingsPayload(
                settingsDraft,
                defaultSettingsDraft,
                editableServerEntries,
              ),
          env: buildChangedFlatPayload(envDraft, savedEnvDraft),
          reset,
        },
      });
      applyOverview(response.data);
      setSaveState("saved");
      window.setTimeout(() => setSaveState("idle"), 1400);
    } catch (error) {
      setSaveState("error");
      setSaveError(getApiErrorMessage(error, "保存设置失败。"));
    }
  }, [
    applyOverview,
    defaultSettingsDraft,
    editableServerEntries,
    envDraft,
    hasEnvChanges,
    hasServerChanges,
    savedEnvDraft,
    settingsDraft,
  ]);

  return {
    overview,
    isOverviewLoading,
    overviewError,
    settingsDraft,
    envDraft,
    defaultSettingsDraft,
    savedEnvDraft,
    hasServerChanges,
    hasEnvChanges,
    saveState,
    saveError,
    patchServerSetting,
    patchEnvSetting,
    resetServerDrafts,
    saveAll,
  };
}

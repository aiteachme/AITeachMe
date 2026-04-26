import { useCallback, useEffect, useState } from "react";

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
} from "./settingsHelpers";
import type {
  ApiEnvelope,
  DraftRecord,
  SaveState,
  SettingEntry,
  SettingSection,
  SettingsOverviewData,
} from "./settingsTypes";

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

interface DraftBundle {
  settingsDraft: DraftRecord;
  savedSettingsDraft: DraftRecord;
  defaultSettingsDraft: DraftRecord;
  envDraft: DraftRecord;
  savedEnvDraft: DraftRecord;
  defaultEnvDraft: DraftRecord;
}

function buildDraftBundle(overview: SettingsOverviewData | null): DraftBundle {
  const sections = overview?.sections ?? [];
  const serverEntries = collectEditableServerEntries(sections);
  const envEntries = collectEditableEnvEntries(sections);
  const settingsDraft = draftFromEntries(serverEntries);
  const envDraft = draftFromEntries(envEntries);

  return {
    settingsDraft,
    savedSettingsDraft: settingsDraft,
    defaultSettingsDraft: draftFromEntries(serverEntries, "default_value"),
    envDraft,
    savedEnvDraft: envDraft,
    defaultEnvDraft: draftFromEntries(envEntries, "default_value"),
  };
}

export function useSettingsOverview({ isOpen }: UseSettingsOverviewOptions) {
  const [initialState] = useState(() => {
    const overview = getStoredSystemSettingsOverview();
    return {
      overview,
      drafts: buildDraftBundle(overview),
    };
  });
  const [overview, setOverview] = useState<SettingsOverviewData | null>(
    initialState.overview,
  );
  const [isOverviewLoading, setIsOverviewLoading] = useState(false);
  const [overviewError, setOverviewError] = useState<string | null>(null);

  const [settingsDraft, setSettingsDraft] = useState<DraftRecord>(
    initialState.drafts.settingsDraft,
  );
  const [savedSettingsDraft, setSavedSettingsDraft] = useState<DraftRecord>(
    initialState.drafts.savedSettingsDraft,
  );
  const [defaultSettingsDraft, setDefaultSettingsDraft] = useState<DraftRecord>(
    initialState.drafts.defaultSettingsDraft,
  );
  const [envDraft, setEnvDraft] = useState<DraftRecord>(
    initialState.drafts.envDraft,
  );
  const [savedEnvDraft, setSavedEnvDraft] = useState<DraftRecord>(
    initialState.drafts.savedEnvDraft,
  );
  const [defaultEnvDraft, setDefaultEnvDraft] = useState<DraftRecord>(
    initialState.drafts.defaultEnvDraft,
  );
  const [resetRequested, setResetRequested] = useState(false);

  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [saveError, setSaveError] = useState<string | null>(null);

  const applyOverview = useCallback((next: SettingsOverviewData) => {
    const drafts = buildDraftBundle(next);

    setOverview(next);
    storeSystemSettingsOverview(next);
    setSettingsDraft(drafts.settingsDraft);
    setSavedSettingsDraft(drafts.savedSettingsDraft);
    setDefaultSettingsDraft(drafts.defaultSettingsDraft);
    setEnvDraft(drafts.envDraft);
    setSavedEnvDraft(drafts.savedEnvDraft);
    setDefaultEnvDraft(drafts.defaultEnvDraft);
    setResetRequested(false);
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

  const editableServerEntries = collectEditableServerEntries(overview?.sections ?? []);
  const hasServerChanges = !sameDraft(settingsDraft, savedSettingsDraft);
  const hasEnvChanges = !sameDraft(envDraft, savedEnvDraft);

  const patchServerSetting = useCallback(
    (key: string, value: DraftRecord[string]) => {
      setResetRequested(false);
      setSettingsDraft((prev) => (prev[key] === value ? prev : { ...prev, [key]: value }));
    },
    [],
  );

  const patchEnvSetting = useCallback(
    (key: string, value: DraftRecord[string]) => {
      setResetRequested(false);
      setEnvDraft((prev) => (prev[key] === value ? prev : { ...prev, [key]: value }));
    },
    [],
  );

  const resetServerDrafts = useCallback(() => {
    setSettingsDraft(defaultSettingsDraft);
    setEnvDraft(defaultEnvDraft);
    setResetRequested(true);
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
      const reset = resetRequested;
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
    resetRequested,
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

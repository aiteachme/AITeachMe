import { memo, useMemo } from "react";

import { InfoCard, SectionDivider } from "./SettingsFields";
import { EditableSettingsList, ReadonlySettingsList } from "./SettingsEntryLists";
import { SETTINGS_STYLES } from "./settingsStyles";
import type { DraftRecord, SettingEntry, SettingSection } from "./settingsTypes";

interface RuntimeSettingsSectionProps {
  section: SettingSection | undefined;
  isLocalRuntime: boolean;
  settingsDraft: DraftRecord;
  envDraft: DraftRecord;
  onServerChange: (key: string, value: DraftRecord[string]) => void;
  onEnvChange: (key: string, value: DraftRecord[string]) => void;
  loading: boolean;
  error: string | null;
}

interface EntryGroup {
  label: string;
  entries: SettingEntry[];
}

interface PreparedEntryGroup {
  label: string;
  serverEditableEntries: SettingEntry[];
  envEditableEntries: SettingEntry[];
  readonlyEntries: SettingEntry[];
}

function compareEntries(a: SettingEntry, b: SettingEntry): number {
  const orderA = Number(a.ui_order ?? 0);
  const orderB = Number(b.ui_order ?? 0);
  if (orderA !== orderB) {
    return orderA - orderB;
  }
  return String(a.label ?? a.key).localeCompare(String(b.label ?? b.key), "zh-CN");
}

function groupSectionEntries(section: SettingSection | undefined): EntryGroup[] {
  const groups = new Map<string, SettingEntry[]>();
  for (const entry of section?.entries ?? []) {
    const label = String(entry.ui_group ?? "").trim();
    const bucket = groups.get(label) ?? [];
    bucket.push(entry);
    groups.set(label, bucket);
  }

  return [...groups.entries()]
    .map(([label, entries]) => ({
      label,
      entries: [...entries].sort(compareEntries),
    }))
    .sort((left, right) => compareEntries(left.entries[0], right.entries[0]));
}

function prepareEntryGroups(
  section: SettingSection | undefined,
  isLocalRuntime: boolean,
): PreparedEntryGroup[] {
  return groupSectionEntries(section).map((group) => ({
    label: group.label,
    envEditableEntries: isLocalRuntime
      ? group.entries.filter((entry) => entry.editable && entry.source === "env")
      : [],
    serverEditableEntries: isLocalRuntime
      ? group.entries.filter((entry) => entry.editable && entry.source !== "env")
      : [],
    readonlyEntries: isLocalRuntime
      ? group.entries.filter((entry) => !entry.editable)
      : group.entries,
  }));
}

export const RuntimeSettingsSection = memo(function RuntimeSettingsSection({
  section,
  isLocalRuntime,
  settingsDraft,
  envDraft,
  onServerChange,
  onEnvChange,
  loading,
  error,
}: RuntimeSettingsSectionProps) {
  if (!section) {
    return <InfoCard text="当前设置分区不存在。" variant="warning" />;
  }

  const groups = useMemo(
    () => prepareEntryGroups(section, isLocalRuntime),
    [isLocalRuntime, section],
  );

  const validGroups = useMemo(
    () =>
      groups.filter(
        (group) =>
          group.serverEditableEntries.length > 0 ||
          group.envEditableEntries.length > 0 ||
          group.readonlyEntries.length > 0,
      ),
    [groups],
  );

  return (
    <div className={SETTINGS_STYLES.section.root}>
      {validGroups.map((group, index) => (
        <div key={`${group.label || "group"}-${index}`} className={SETTINGS_STYLES.section.groupBlock}>
          {group.label ? <SectionDivider label={group.label} compact={index === 0} /> : null}

          <div className={SETTINGS_STYLES.section.cardWrapper}>
            {group.serverEditableEntries.length > 0 ? (
              <EditableSettingsList
                entries={group.serverEditableEntries}
                draft={settingsDraft}
                onChange={onServerChange}
                loading={loading}
                error={error}
              />
            ) : null}

            {group.envEditableEntries.length > 0 ? (
              <EditableSettingsList
                entries={group.envEditableEntries}
                draft={envDraft}
                onChange={onEnvChange}
                loading={loading}
                error={error}
              />
            ) : null}

            {group.readonlyEntries.length > 0 ? (
              <ReadonlySettingsList
                entries={group.readonlyEntries}
                loading={loading}
                error={error}
              />
            ) : null}
          </div>
        </div>
      ))}
    </div>
  );
});

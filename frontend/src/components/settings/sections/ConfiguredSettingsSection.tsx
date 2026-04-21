import { SETTINGS_STYLES } from "../constants";
import { InfoCard, SectionDivider } from "../fields";
import { EditableSettingsList, ReadonlySettingsList } from "../lists";
import type { DraftRecord, SettingEntry, SettingSection } from "../types";

interface ConfiguredSettingsSectionProps {
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

export function ConfiguredSettingsSection({
  section,
  isLocalRuntime,
  settingsDraft,
  envDraft,
  onServerChange,
  onEnvChange,
  loading,
  error,
}: ConfiguredSettingsSectionProps) {
  if (!section) {
    return <InfoCard text="当前设置分区不存在。" variant="warning" />;
  }

  const groups = groupSectionEntries(section);

  return (
    <div className={SETTINGS_STYLES.section.root}>
      {groups.map((group, index) => {
        const envEditableEntries = isLocalRuntime
          ? group.entries.filter((entry) => entry.editable && entry.source === "env")
          : [];
        const serverEditableEntries = isLocalRuntime
          ? group.entries.filter((entry) => entry.editable && entry.source !== "env")
          : [];
        const readonlyEntries = isLocalRuntime
          ? group.entries.filter((entry) => !entry.editable)
          : group.entries;

        return (
          <div key={`${group.label || "group"}-${index}`} className={SETTINGS_STYLES.section.groupBlock}>
            {group.label ? <SectionDivider label={group.label} /> : null}

            {serverEditableEntries.length > 0 ? (
              <EditableSettingsList
                entries={serverEditableEntries}
                draft={settingsDraft}
                onChange={onServerChange}
                loading={loading}
                error={error}
              />
            ) : null}

            {envEditableEntries.length > 0 ? (
              <EditableSettingsList
                entries={envEditableEntries}
                draft={envDraft}
                onChange={onEnvChange}
                loading={loading}
                error={error}
              />
            ) : null}

            {readonlyEntries.length > 0 ? (
              <ReadonlySettingsList
                entries={readonlyEntries}
                loading={loading}
                error={error}
              />
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

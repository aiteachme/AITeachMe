import { memo } from "react";

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

interface PreparedEntryGroup {
  label: string;
  serverEditableEntries: SettingEntry[];
  envEditableEntries: SettingEntry[];
  readonlyEntries: SettingEntry[];
}

function renderGroupNote(label: string) {
  if (label === "解析服务授权") {
    return (
      <p className={SETTINGS_STYLES.section.groupNote}>
        填入 PaddleOCR 或 MinerU Token 后，支持的文档会优先尝试 PaddleOCR，再回退到 MinerU，最后回退到本地解析；未配置时直接使用本地解析。
      </p>
    );
  }
  return null;
}

function compareEntries(a: SettingEntry, b: SettingEntry): number {
  const orderA = Number(a.ui_order ?? 0);
  const orderB = Number(b.ui_order ?? 0);
  if (orderA !== orderB) {
    return orderA - orderB;
  }
  return String(a.label ?? a.key).localeCompare(String(b.label ?? b.key), "zh-CN");
}

function buildEntryGroups(
  section: SettingSection | undefined,
  isLocalRuntime: boolean,
): PreparedEntryGroup[] {
  const groups = new Map<string, SettingEntry[]>();
  for (const entry of section?.entries ?? []) {
    const label = String(entry.ui_group ?? "").trim();
    const bucket = groups.get(label) ?? [];
    bucket.push(entry);
    groups.set(label, bucket);
  }

  return [...groups.entries()]
    .map(([label, entries]) => {
      const sortedEntries = [...entries].sort(compareEntries);
      return {
        label,
        envEditableEntries: isLocalRuntime
          ? sortedEntries.filter((entry) => entry.editable && entry.source === "env")
          : [],
        serverEditableEntries: isLocalRuntime
          ? sortedEntries.filter((entry) => entry.editable && entry.source !== "env")
          : [],
        readonlyEntries: isLocalRuntime
          ? sortedEntries.filter((entry) => !entry.editable)
          : sortedEntries,
      };
    })
    .filter(
      (group) =>
        group.serverEditableEntries.length > 0 ||
        group.envEditableEntries.length > 0 ||
        group.readonlyEntries.length > 0,
    )
    .sort((left, right) => {
      const leftEntry =
        left.serverEditableEntries[0] ?? left.envEditableEntries[0] ?? left.readonlyEntries[0];
      const rightEntry =
        right.serverEditableEntries[0] ?? right.envEditableEntries[0] ?? right.readonlyEntries[0];
      return compareEntries(leftEntry, rightEntry);
    });
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

  const groups = buildEntryGroups(section, isLocalRuntime);

  return (
    <div className={SETTINGS_STYLES.section.root}>
      {groups.map((group, index) => (
        <div key={`${group.label || "group"}-${index}`} className={SETTINGS_STYLES.section.groupBlock}>
          {group.label ? <SectionDivider label={group.label} compact={index === 0} /> : null}
          {renderGroupNote(group.label)}

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

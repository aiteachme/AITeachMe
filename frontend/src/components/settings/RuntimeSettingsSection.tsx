import { memo } from "react";

import { InfoCard, SectionDivider } from "./SettingsFields";
import { EditableSettingsRow, ReadonlySettingsRow } from "./SettingsEntryLists";
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
  entries: SettingEntry[];
}

function renderGroupNote(label: string) {
  if (label === "文本生成") {
    return (
      <p className={SETTINGS_STYLES.section.groupNote}>
        主文本模型影响日常对话与生成；推理模型用于规划和复杂讲解；轻量模型用于标题、分类、摘要等快速任务。
      </p>
    );
  }
  if (label === "统一模型接入") {
    return (
      <p className={SETTINGS_STYLES.section.groupNote}>
        模型网关密钥和地址优先配置；接口模式、推理强度和并发限制按上游能力微调。
      </p>
    );
  }
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
        entries: isLocalRuntime ? sortedEntries : sortedEntries.map((entry) => ({
          ...entry,
          editable: false,
        })),
      };
    })
    .filter((group) => group.entries.length > 0)
    .sort((left, right) => {
      return compareEntries(left.entries[0], right.entries[0]);
    });
}

function RuntimeSettingsGroupList({
  entries,
  settingsDraft,
  envDraft,
  onServerChange,
  onEnvChange,
  loading,
  error,
}: {
  entries: SettingEntry[];
  settingsDraft: DraftRecord;
  envDraft: DraftRecord;
  onServerChange: (key: string, value: DraftRecord[string]) => void;
  onEnvChange: (key: string, value: DraftRecord[string]) => void;
  loading: boolean;
  error: string | null;
}) {
  if (loading) return <InfoCard text="正在读取后端当前状态..." />;
  if (error) return <InfoCard text={error} variant="warning" />;
  if (!entries.length) return null;

  return (
    <div className={SETTINGS_STYLES.list.root}>
      {entries.map((entry) => {
        if (!entry.editable) {
          return <ReadonlySettingsRow key={entry.key} entry={entry} />;
        }
        const isEnvEntry = entry.source === "env";
        return (
          <EditableSettingsRow
            key={entry.key}
            entry={entry}
            value={(isEnvEntry ? envDraft : settingsDraft)[entry.key] ?? null}
            onChange={isEnvEntry ? onEnvChange : onServerChange}
          />
        );
      })}
    </div>
  );
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
            <RuntimeSettingsGroupList
              entries={group.entries}
              settingsDraft={settingsDraft}
              envDraft={envDraft}
              onServerChange={onServerChange}
              onEnvChange={onEnvChange}
              loading={loading}
              error={error}
            />
          </div>
        </div>
      ))}
    </div>
  );
});

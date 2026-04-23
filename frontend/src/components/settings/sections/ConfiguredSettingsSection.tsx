import { useMemo } from "react";

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
  settingsDraft: DraftRecord,
): PreparedEntryGroup[] {
  return groupSectionEntries(section).map((group) => {
    const entries = filterParserServiceEntries(group.entries, settingsDraft);
    return {
      label: group.label,
      envEditableEntries: isLocalRuntime
        ? entries.filter((entry) => entry.editable && entry.source === "env")
        : [],
      serverEditableEntries: isLocalRuntime
        ? entries.filter((entry) => entry.editable && entry.source !== "env")
        : [],
      readonlyEntries: isLocalRuntime
        ? entries.filter((entry) => !entry.editable)
        : entries,
    };
  });
}

function resolveParserProvider(entries: SettingEntry[], settingsDraft: DraftRecord): string {
  const draftValue = settingsDraft["ingest.parser_provider"];
  if (typeof draftValue === "string" && draftValue.trim()) {
    return draftValue.trim().toLowerCase();
  }
  const entryValue = entries.find((entry) => entry.key === "ingest.parser_provider")?.value;
  if (typeof entryValue === "string" && entryValue.trim()) {
    return entryValue.trim().toLowerCase();
  }
  return "local";
}

function filterParserServiceEntries(entries: SettingEntry[], settingsDraft: DraftRecord): SettingEntry[] {
  if (!entries.some((entry) => entry.key === "ingest.parser_provider")) {
    return entries;
  }
  const provider = resolveParserProvider(entries, settingsDraft);
  const alwaysVisible = new Set(["ingest.parser_provider"]);
  const mineruVisible = new Set(["mineru.api_token"]);
  const paddleOcrVisible = new Set(["paddle_ocr.api_token"]);
  const ocrVisible = new Set(["ocr.base_url", "ocr.api_key", "models.ocr"]);

  return entries.filter((entry) => {
    if (alwaysVisible.has(entry.key)) return true;
    if (provider === "mineru") return mineruVisible.has(entry.key);
    if (provider === "paddle_ocr") return paddleOcrVisible.has(entry.key);
    if (provider === "ocr") return ocrVisible.has(entry.key);
    return false;
  });
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

  const groups = useMemo(
    () => prepareEntryGroups(section, isLocalRuntime, settingsDraft),
    [isLocalRuntime, section, settingsDraft],
  );

  return (
    <div className={SETTINGS_STYLES.section.root}>
      {groups.map((group, index) => {
        return (
          <div key={`${group.label || "group"}-${index}`} className={SETTINGS_STYLES.section.groupBlock}>
            {group.label ? <SectionDivider label={group.label} /> : null}

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
        );
      })}
    </div>
  );
}

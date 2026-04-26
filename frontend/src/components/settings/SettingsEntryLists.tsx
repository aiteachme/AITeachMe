import { memo, useCallback, useEffect, useMemo, useState } from "react";

import {
  FieldLabelBlock,
  InfoCard,
  ReadonlyValue,
  SecretInput,
  SelectInput,
  SwitchRow,
  TextInput,
} from "./SettingsFields";
import { SETTING_SELECT_OPTIONS, SETTINGS_STYLES } from "./settingsStyles";
import {
  displayValue,
  isPrimitive,
  parseInputValue,
  resolveEntryInputType,
} from "./settingsHelpers";
import type { DraftRecord, SettingEntry, SettingPrimitive } from "./settingsTypes";

function renderEntryHelper(entryKey: string) {
  if (entryKey === "mineru.api_token") {
    return (
      <a
        href="https://mineru.net/apiManage/token"
        target="_blank"
        rel="noreferrer"
        className="text-xs font-medium text-sky-600 underline underline-offset-4 transition-colors hover:text-sky-700"
      >
        去 MinerU 获取 API Token
      </a>
    );
  }
  if (entryKey === "paddle_ocr.api_token") {
    return (
      <a
        href="https://aistudio.baidu.com/account/accessToken"
        target="_blank"
        rel="noreferrer"
        className="text-xs font-medium text-sky-600 underline underline-offset-4 transition-colors hover:text-sky-700"
      >
        去 PaddleOCR 获取 API Token
      </a>
    );
  }
  return null;
}

interface ReadonlySettingsListProps {
  entries: SettingEntry[];
  loading: boolean;
  error: string | null;
}

const ReadonlySettingsRow = memo(function ReadonlySettingsRow({
  entry,
}: {
  entry: SettingEntry;
}) {
  return (
    <div className={SETTINGS_STYLES.list.readonlyItem}>
      <FieldLabelBlock
        label={entry.label}
        description={entry.description}
        helper={renderEntryHelper(entry.key)}
      />
      <div className={SETTINGS_STYLES.list.readonlyControl}>
        <ReadonlyValue>{displayValue(entry)}</ReadonlyValue>
      </div>
    </div>
  );
});

export function ReadonlySettingsList({
  entries,
  loading,
  error,
}: ReadonlySettingsListProps) {
  if (loading) return <InfoCard text="正在读取后端当前状态..." />;
  if (error) return <InfoCard text={error} variant="warning" />;
  if (!entries.length) return null;

  return (
    <div className={SETTINGS_STYLES.list.root}>
      {entries.map((entry) => (
        <ReadonlySettingsRow key={entry.key} entry={entry} />
      ))}
    </div>
  );
}

interface EditableSettingsListProps {
  entries: SettingEntry[];
  draft: DraftRecord;
  onChange: (key: string, value: SettingPrimitive) => void;
  loading: boolean;
  error: string | null;
}

interface EditableSettingsRowProps {
  entry: SettingEntry;
  value: SettingPrimitive;
  onChange: (key: string, value: SettingPrimitive) => void;
}

const EditableSettingsRow = memo(function EditableSettingsRow({
  entry,
  value,
  onChange,
}: EditableSettingsRowProps) {
  const selectOptions = useMemo(() => SETTING_SELECT_OPTIONS[entry.key], [entry.key]);
  const controlId = `settings-${entry.key.replace(/[^a-z0-9]+/gi, "-").toLowerCase()}`;
  const resolvedInputType = resolveEntryInputType(entry, value);
  const [localValue, setLocalValue] = useState(() => (value === null ? "" : String(value)));

  useEffect(() => {
    const nextValue = value === null ? "" : String(value);
    setLocalValue((prev) => (prev === nextValue ? prev : nextValue));
  }, [value]);

  const handleBooleanToggle = useCallback(() => {
    if (typeof value === "boolean") {
      onChange(entry.key, !value);
    }
  }, [entry.key, onChange, value]);

  const handleValueChange = useCallback((next: string) => {
    setLocalValue((prev) => (prev === next ? prev : next));
  }, []);

  const commitLocalValue = useCallback(() => {
    if (typeof value === "boolean" || selectOptions) {
      return;
    }
    const parsed = parseInputValue(localValue, value);
    if (parsed === value) {
      return;
    }
    onChange(entry.key, parsed);
  }, [entry.key, localValue, onChange, selectOptions, value]);

  const handleSelectChange = useCallback(
    (next: string) => {
      setLocalValue(next);
      onChange(entry.key, next);
    },
    [entry.key, onChange],
  );

  if (typeof value === "boolean") {
    return (
      <div>
        <SwitchRow
          title={entry.label}
          description={entry.description || entry.key}
          enabled={value}
          onToggle={handleBooleanToggle}
        />
      </div>
    );
  }

  return (
    <div className={SETTINGS_STYLES.list.item}>
      <FieldLabelBlock
        label={entry.label}
        description={entry.description}
        helper={renderEntryHelper(entry.key)}
        htmlFor={controlId}
      />

      <div className={SETTINGS_STYLES.list.controlWrap}>
        {selectOptions ? (
          <SelectInput
            id={controlId}
            value={localValue}
            onChange={handleSelectChange}
            options={selectOptions}
          />
        ) : resolvedInputType === "password" ? (
          <SecretInput
            id={controlId}
            value={localValue}
            onChange={handleValueChange}
            onBlur={commitLocalValue}
            placeholder={
              entry.default_value === null || entry.default_value === undefined
                ? "留空"
                : String(entry.default_value)
            }
          />
        ) : (
          <TextInput
            id={controlId}
            value={localValue}
            onChange={handleValueChange}
            onBlur={commitLocalValue}
            placeholder={
              entry.default_value === null || entry.default_value === undefined
                ? "留空"
                : String(entry.default_value)
            }
            type={resolvedInputType}
          />
        )}
      </div>
    </div>
  );
}, (prev, next) => (
  prev.entry === next.entry &&
  prev.value === next.value &&
  prev.onChange === next.onChange
));

export function EditableSettingsList({
  entries,
  draft,
  onChange,
  loading,
  error,
}: EditableSettingsListProps) {
  const items = entries.filter((entry) => entry.editable && isPrimitive(draft[entry.key]));
  if (loading) return <InfoCard text="正在加载..." />;
  if (error) return <InfoCard text={error} variant="warning" />;
  if (!items.length) return null;

  return (
    <div className={SETTINGS_STYLES.list.root}>
      {items.map((entry) => {
        const value = draft[entry.key];
        return (
          <EditableSettingsRow
            key={entry.key}
            entry={entry}
            value={value}
            onChange={onChange}
          />
        );
      })}
    </div>
  );
}

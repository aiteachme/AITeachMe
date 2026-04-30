import { memo, useCallback, useEffect, useMemo, useState } from "react";

import {
  BundledSecretValue,
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
  isBundledSecretEntry,
  isConfiguredSecretEntry,
  isPrimitive,
  parseInputValue,
  resolveEntryInputType,
  SECRET_DISPLAY_MASK,
  SECRET_PRESERVE_VALUE,
} from "./settingsHelpers";
import type { DraftRecord, SettingEntry, SettingPrimitive } from "./settingsTypes";

function displayDraftValue(value: SettingPrimitive, isSavedSecretDraft: boolean): string {
  if (isSavedSecretDraft) return SECRET_DISPLAY_MASK;
  if (value === null) return "";
  return String(value);
}

function revealSecretValue(entry: SettingEntry): string | null {
  return typeof entry.reveal_value === "string" && entry.reveal_value.length > 0
    ? entry.reveal_value
    : null;
}

function renderEntryHelper(entryKey: string) {
  if (entryKey === "mineru.api_token") {
    return (
      <a
        href="https://mineru.net/apiManage/token"
        target="_blank"
        rel="noreferrer"
        className="text-xs font-medium text-indigo-600 underline underline-offset-4 transition-colors hover:text-indigo-700"
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
        className="text-xs font-medium text-indigo-600 underline underline-offset-4 transition-colors hover:text-indigo-700"
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
        {isBundledSecretEntry(entry) ? (
          <BundledSecretValue />
        ) : (
          <ReadonlyValue>{displayValue(entry)}</ReadonlyValue>
        )}
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
  const isConfiguredSecret = isConfiguredSecretEntry(entry);
  const isBundledSecret = isBundledSecretEntry(entry);
  const isSavedSecretDraft = isConfiguredSecret && value === SECRET_PRESERVE_VALUE;
  const isSecretInput = resolvedInputType === "password";
  const secretRevealValue = revealSecretValue(entry);
  const [localValue, setLocalValue] = useState(() =>
    displayDraftValue(value, isSavedSecretDraft),
  );
  const [isReplacingSavedSecret, setIsReplacingSavedSecret] = useState(false);
  const isShowingSavedSecretMask = Boolean(isSavedSecretDraft && !isReplacingSavedSecret);

  useEffect(() => {
    const nextValue = displayDraftValue(value, isSavedSecretDraft);
    setLocalValue((prev) => (prev === nextValue ? prev : nextValue));
    if (!isSavedSecretDraft) {
      setIsReplacingSavedSecret(false);
    }
  }, [isSavedSecretDraft, value]);

  const handleBooleanToggle = useCallback(() => {
    if (typeof value === "boolean") {
      onChange(entry.key, !value);
    }
  }, [entry.key, onChange, value]);

  const handleValueChange = useCallback((next: string) => {
    if (!isSecretInput) {
      setLocalValue((prev) => (prev === next ? prev : next));
      return;
    }

    let nextSecret = next;
    if (isSavedSecretDraft && !isReplacingSavedSecret) {
      const isUserReplacingMask = next !== SECRET_DISPLAY_MASK;
      nextSecret = nextSecret.replace(SECRET_DISPLAY_MASK, "");
      setIsReplacingSavedSecret(isUserReplacingMask);
    }

    setLocalValue((prev) => (prev === nextSecret ? prev : nextSecret));
    if (isSavedSecretDraft && !isReplacingSavedSecret && next === SECRET_DISPLAY_MASK) {
      onChange(entry.key, SECRET_PRESERVE_VALUE);
      return;
    }
    onChange(entry.key, parseInputValue(nextSecret, isSavedSecretDraft ? null : value));
  }, [
    entry.key,
    isSavedSecretDraft,
    isSecretInput,
    isReplacingSavedSecret,
    onChange,
    value,
  ]);

  const handleSecretFocus = useCallback(() => {
    if (isShowingSavedSecretMask) {
      setLocalValue(SECRET_DISPLAY_MASK);
    }
  }, [isShowingSavedSecretMask]);

  const commitLocalValue = useCallback(() => {
    if (typeof value === "boolean" || selectOptions) {
      return;
    }
    if (
      isSavedSecretDraft &&
      (!isReplacingSavedSecret || localValue === SECRET_DISPLAY_MASK)
    ) {
      setIsReplacingSavedSecret(false);
      setLocalValue(SECRET_DISPLAY_MASK);
      onChange(entry.key, SECRET_PRESERVE_VALUE);
      return;
    }
    const parsed = parseInputValue(localValue, isSavedSecretDraft ? null : value);
    if (parsed === value) {
      return;
    }
    onChange(entry.key, parsed);
  }, [
    entry.key,
    isSavedSecretDraft,
    isReplacingSavedSecret,
    localValue,
    onChange,
    selectOptions,
    value,
  ]);

  const handleSelectChange = useCallback(
    (next: string) => {
      setLocalValue(next);
      onChange(entry.key, next);
    },
    [entry.key, onChange],
  );

  const secretStatusText = isShowingSavedSecretMask
    ? "当前已保存，留空不会修改。"
    : isConfiguredSecret && isReplacingSavedSecret && !localValue.trim()
      ? "保存后将清空设置页覆盖，并回落到 .env 或默认值。"
      : undefined;

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

  if (isBundledSecret && isSavedSecretDraft) {
    return (
      <div className={SETTINGS_STYLES.list.item}>
        <FieldLabelBlock
          label={entry.label}
          description={entry.description}
          helper={renderEntryHelper(entry.key)}
        />
        <div className={SETTINGS_STYLES.list.controlWrap}>
          <BundledSecretValue />
        </div>
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
            onFocus={handleSecretFocus}
            onBlur={commitLocalValue}
            placeholder={
              isConfiguredSecret
                ? "输入新值可替换"
                : entry.default_value === null || entry.default_value === undefined
                  ? "请输入 Token"
                  : String(entry.default_value)
            }
            revealValue={isShowingSavedSecretMask ? secretRevealValue : undefined}
            selectOnFocus={isShowingSavedSecretMask}
            showToggle={
              (isShowingSavedSecretMask && secretRevealValue !== null) ||
              (!isShowingSavedSecretMask && localValue.length > 0)
            }
            statusText={secretStatusText}
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

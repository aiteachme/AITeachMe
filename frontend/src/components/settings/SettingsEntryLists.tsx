import { memo, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { apiClient } from "../../api/client";
import type { ModelReasoningCapabilitiesResult } from "../../api/generated/model/modelReasoningCapabilitiesResult";

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
import type { ApiEnvelope, DraftRecord, SettingEntry, SettingPrimitive } from "./settingsTypes";

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

export const ReadonlySettingsRow = memo(function ReadonlySettingsRow({
  entry,
  inlineEntry,
}: {
  entry: SettingEntry;
  inlineEntry?: SettingEntry;
}) {
  const visibleInlineEntry = inlineEntry && (
    entryOptions(inlineEntry).length || hasInlineValue(inlineEntry.value)
  ) ? inlineEntry : undefined;
  return (
    <div className={SETTINGS_STYLES.list.readonlyItem}>
      <FieldLabelBlock
        label={entry.label}
        description={entry.description}
        helper={renderEntryHelper(entry.key)}
      />
      <div className={SETTINGS_STYLES.list.readonlyControl}>
        <div className={visibleInlineEntry ? SETTINGS_STYLES.list.pairedControls : undefined}>
          <div>
            {isBundledSecretEntry(entry) ? (
              <BundledSecretValue />
            ) : (
              <ReadonlyValue>{displayValue(entry)}</ReadonlyValue>
            )}
          </div>
          {visibleInlineEntry ? <InlineSettingControl entry={visibleInlineEntry} /> : null}
        </div>
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
  afterControl?: ReactNode;
  commitTextOnChange?: boolean;
  inlineFallbackValue?: string;
  inlineEntry?: SettingEntry;
  inlineValue?: SettingPrimitive;
  onInlineChange?: (key: string, value: SettingPrimitive) => void;
}

const REASONING_CAPABILITY_DEBOUNCE_MS = 120;
const reasoningOptionsCache = new Map<
  string,
  Array<{ value: string | null; label: string }>
>();

function entryOptions(entry: SettingEntry | undefined) {
  if (!entry) return [];
  return entry.options?.length ? entry.options : SETTING_SELECT_OPTIONS[entry.key] ?? [];
}

function reasoningOptions(efforts: string[] | null | undefined) {
  if (!efforts?.length) return [];
  return [
    { value: null, label: "模型默认" },
    ...efforts.map((effort) => ({ value: effort, label: effort })),
  ];
}

function hasInlineValue(value: unknown): value is Exclude<SettingPrimitive, null> {
  return isPrimitive(value) && value !== null && (typeof value !== "string" || value.trim().length > 0);
}

function useLiveInlineEntry(
  entry: SettingEntry | undefined,
  parentValue: string,
  value: SettingPrimitive | undefined,
): SettingEntry | undefined {
  const modelKey = parentValue.trim().toLowerCase();
  const previousModelKeyRef = useRef(modelKey);
  const previousServerOptionsRef = useRef(entry?.options);
  const [options, setOptions] = useState(() => entryOptions(entry));

  useEffect(() => {
    if (previousServerOptionsRef.current === entry?.options) {
      return;
    }
    previousServerOptionsRef.current = entry?.options;
    const nextOptions = entryOptions(entry);
    setOptions(nextOptions);
    if (modelKey) {
      reasoningOptionsCache.set(modelKey, nextOptions);
    }
  }, [entry?.options, modelKey]);

  useEffect(() => {
    if (!entry || !entry.key.startsWith("llm.reasoning_efforts.")) {
      setOptions(entryOptions(entry));
      return;
    }
    if (previousModelKeyRef.current === modelKey) {
      return;
    }
    previousModelKeyRef.current = modelKey;

    if (!modelKey) {
      setOptions([]);
      return;
    }

    const cachedOptions = reasoningOptionsCache.get(modelKey);
    if (cachedOptions) {
      setOptions(cachedOptions);
      return;
    }

    setOptions([]);
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      try {
        const response = await apiClient<ApiEnvelope<ModelReasoningCapabilitiesResult>>({
          url: "/api/v1/system/settings/model-capabilities/reasoning",
          method: "GET",
          params: { model: modelKey },
          signal: controller.signal,
        });
        const nextOptions = reasoningOptions(response.data.reasoning_efforts);
        reasoningOptionsCache.set(modelKey, nextOptions);
        if (!controller.signal.aborted) {
          setOptions(nextOptions);
        }
      } catch {
        if (!controller.signal.aborted) {
          setOptions([]);
        }
      }
    }, REASONING_CAPABILITY_DEBOUNCE_MS);

    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [entry?.key, modelKey]);

  return useMemo(() => {
    if (!entry || (!options.length && !hasInlineValue(value))) return undefined;
    return entry.options === options ? entry : { ...entry, options };
  }, [entry, options, value]);
}

function InlineSettingControl({
  entry,
  value,
  onChange,
}: {
  entry: SettingEntry;
  value?: SettingPrimitive;
  onChange?: (key: string, value: SettingPrimitive) => void;
}) {
  const options = entryOptions(entry);
  const rawValue = value === undefined && isPrimitive(entry.value) ? entry.value : value;
  const resolvedValue = typeof rawValue === "string" ? rawValue : null;
  const selectedLabel = options.find((option) => option.value === resolvedValue)?.label;

  if (!options.length) {
    if (!hasInlineValue(resolvedValue)) return null;
    return (
      <ReadonlyValue className="flex min-h-11 items-center gap-2 whitespace-nowrap">
        <span className="text-[12px] text-zinc-400 dark:text-slate-500">推理强度</span>
        <span className="min-w-0 truncate">{resolvedValue}</span>
      </ReadonlyValue>
    );
  }

  const controlId = `settings-${entry.key.replace(/[^a-z0-9]+/gi, "-").toLowerCase()}`;

  if (!entry.editable || !onChange) {
    return (
      <ReadonlyValue
        className="flex min-h-11 items-center gap-2 whitespace-nowrap"
      >
        <span className="text-[12px] text-zinc-400 dark:text-slate-500">推理强度</span>
        <span className="min-w-0 truncate">{selectedLabel ?? displayValue(entry)}</span>
      </ReadonlyValue>
    );
  }

  return (
    <div className={SETTINGS_STYLES.list.inlineControl} title={entry.description}>
      <label htmlFor={controlId} className="sr-only">
        {entry.label}
      </label>
      <SelectInput
        id={controlId}
        value={resolvedValue}
        onChange={(next) => onChange(entry.key, next)}
        options={options}
        prefixLabel="推理强度"
      />
    </div>
  );
}

export const EditableSettingsRow = memo(function EditableSettingsRow({
  entry,
  value,
  onChange,
  afterControl,
  commitTextOnChange = false,
  inlineFallbackValue,
  inlineEntry,
  inlineValue,
  onInlineChange,
}: EditableSettingsRowProps) {
  const selectOptions = useMemo(
    () => entry.options?.length ? entry.options : SETTING_SELECT_OPTIONS[entry.key],
    [entry.key, entry.options],
  );
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
  const liveInlineEntry = useLiveInlineEntry(
    inlineEntry,
    localValue.trim() || inlineFallbackValue || "",
    inlineValue,
  );
  const inlineEntryKey = inlineEntry?.key;

  useEffect(() => {
    const nextValue = displayDraftValue(value, isSavedSecretDraft);
    setLocalValue((prev) => (prev === nextValue ? prev : nextValue));
    if (!isSavedSecretDraft) {
      setIsReplacingSavedSecret(false);
    }
  }, [isSavedSecretDraft, value]);

  useEffect(() => {
    if (
      !liveInlineEntry ||
      !onInlineChange ||
      inlineValue === null ||
      inlineValue === undefined
    ) {
      return;
    }
    const isStillSupported = entryOptions(liveInlineEntry).some(
      (option) => option.value === inlineValue,
    );
    if (!isStillSupported) {
      onInlineChange(liveInlineEntry.key, null);
    }
  }, [inlineValue, liveInlineEntry, onInlineChange]);

  const handleBooleanToggle = useCallback(() => {
    if (typeof value === "boolean") {
      onChange(entry.key, !value);
    }
  }, [entry.key, onChange, value]);

  const handleValueChange = useCallback((next: string) => {
    if (!isSecretInput) {
      setLocalValue((prev) => (prev === next ? prev : next));
      if (commitTextOnChange) {
        onChange(entry.key, parseInputValue(next, value));
        if (
          inlineEntryKey &&
          onInlineChange &&
          inlineValue !== null &&
          inlineValue !== undefined
        ) {
          onInlineChange(inlineEntryKey, null);
        }
      }
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
    commitTextOnChange,
    isSavedSecretDraft,
    isSecretInput,
    isReplacingSavedSecret,
    inlineEntryKey,
    inlineValue,
    onChange,
    onInlineChange,
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
    (next: string | null) => {
      setLocalValue(next ?? "");
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
        <div className={liveInlineEntry ? SETTINGS_STYLES.list.pairedControls : undefined}>
          <div>
            {selectOptions ? (
              <SelectInput
                id={controlId}
                value={value === null ? null : localValue}
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
          {liveInlineEntry ? (
            <InlineSettingControl
              entry={liveInlineEntry}
              value={inlineValue}
              onChange={onInlineChange}
            />
          ) : null}
        </div>
        {afterControl ? <div className="mt-3">{afterControl}</div> : null}
      </div>
    </div>
  );
}, (prev, next) => (
  prev.entry === next.entry &&
  prev.value === next.value &&
  prev.onChange === next.onChange &&
  prev.afterControl === next.afterControl &&
  prev.commitTextOnChange === next.commitTextOnChange &&
  prev.inlineFallbackValue === next.inlineFallbackValue &&
  prev.inlineEntry === next.inlineEntry &&
  prev.inlineValue === next.inlineValue &&
  prev.onInlineChange === next.onInlineChange
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

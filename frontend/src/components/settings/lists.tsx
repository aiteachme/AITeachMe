import {
  FieldLabelBlock,
  InfoCard,
  ReadonlyValue,
  SecretInput,
  SelectInput,
  SwitchRow,
  TextInput,
} from "./fields";
import { SETTINGS_STYLES, SETTING_SELECT_OPTIONS } from "./constants";
import {
  displayValue,
  isPrimitive,
  parseInputValue,
  resolveEntryInputType,
} from "./helpers";
import type { DraftRecord, SettingEntry, SettingPrimitive } from "./types";

interface ReadonlySettingsListProps {
  entries: SettingEntry[];
  loading: boolean;
  error: string | null;
}

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
        <div key={entry.key} className={SETTINGS_STYLES.list.readonlyItem}>
          <FieldLabelBlock
            label={entry.label}
            description={entry.description}
          />
          <div className={SETTINGS_STYLES.list.readonlyControl}>
            <ReadonlyValue>
              {displayValue(entry)}
            </ReadonlyValue>
          </div>
        </div>
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

export function EditableSettingsList({
  entries,
  draft,
  onChange,
  loading,
  error,
}: EditableSettingsListProps) {
  const items = entries.filter(
    (entry) => entry.editable && isPrimitive(draft[entry.key]),
  );
  if (loading) return <InfoCard text="正在加载..." />;
  if (error) return <InfoCard text={error} variant="warning" />;
  if (!items.length) return null;

  return (
    <div className={SETTINGS_STYLES.list.root}>
      {items.map((entry) => {
        const value = draft[entry.key];
        const selectOptions = SETTING_SELECT_OPTIONS[entry.key];
        const controlId = `settings-${entry.key.replace(/[^a-z0-9]+/gi, "-").toLowerCase()}`;

        if (typeof value === "boolean") {
          return (
            <div key={entry.key}>
              <SwitchRow
                title={entry.label}
                description={entry.description || entry.key}
                enabled={value}
                onToggle={() => onChange(entry.key, !value)}
              />
            </div>
          );
        }

        return (
          <div key={entry.key} className={SETTINGS_STYLES.list.item}>
            <FieldLabelBlock
              label={entry.label}
              description={entry.description}
              htmlFor={controlId}
            />

            <div className={SETTINGS_STYLES.list.controlWrap}>
              {selectOptions ? (
                <SelectInput
                  id={controlId}
                  value={value === null ? "" : String(value)}
                  onChange={(next) => onChange(entry.key, next)}
                  options={selectOptions}
                />
              ) : resolveEntryInputType(entry, value) === "password" ? (
                <SecretInput
                  id={controlId}
                  value={value === null ? "" : String(value)}
                  onChange={(next) => onChange(entry.key, parseInputValue(next, value))}
                  placeholder={
                    entry.default_value === null || entry.default_value === undefined
                      ? "留空"
                      : String(entry.default_value)
                  }
                />
              ) : (
                <TextInput
                  id={controlId}
                  value={value === null ? "" : String(value)}
                  onChange={(next) => onChange(entry.key, parseInputValue(next, value))}
                  placeholder={
                    entry.default_value === null || entry.default_value === undefined
                      ? "留空"
                      : String(entry.default_value)
                  }
                  type={resolveEntryInputType(entry, value)}
                />
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

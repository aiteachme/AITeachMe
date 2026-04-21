import { InfoCard, SelectInput, SwitchRow, TextInput } from "./fields";
import { SETTING_SELECT_OPTIONS } from "./constants";
import { displayValue, isPrimitive, parseInputValue } from "./helpers";
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
    <div className="space-y-6">
      {entries.map((entry) => (
        <div key={entry.key} className="space-y-2">
          <div className="flex flex-col gap-1.5">
            <span className="text-sm font-medium leading-none text-zinc-900 block">
              {entry.label}
            </span>
            {entry.description && (
              <p className="text-[13px] text-zinc-500 leading-relaxed">
                {entry.description}
              </p>
            )}
          </div>
          <div className="font-mono text-[13px] text-zinc-800 bg-zinc-50/80 px-3 py-1.5 rounded-md border border-zinc-200 break-all w-fit max-w-full shadow-sm">
            {displayValue(entry)}
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
    <div className="space-y-6">
      {items.map((entry) => {
        const value = draft[entry.key];
        const selectOptions = SETTING_SELECT_OPTIONS[entry.key];

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
          <div key={entry.key} className="space-y-2">
            <div className="flex flex-col gap-1.5">
              <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70 text-zinc-900">
                {entry.label}
              </label>
              {entry.description && (
                <p className="text-[13px] text-zinc-500 leading-relaxed">
                  {entry.description}
                </p>
              )}
            </div>

            <div className="w-full">
              {selectOptions ? (
                <SelectInput
                  value={value === null ? "" : String(value)}
                  onChange={(next) => onChange(entry.key, next)}
                  options={selectOptions}
                />
              ) : (
                <TextInput
                  value={value === null ? "" : String(value)}
                  onChange={(next) => onChange(entry.key, parseInputValue(next, value))}
                  placeholder={
                    entry.default_value === null || entry.default_value === undefined
                      ? "留空"
                      : String(entry.default_value)
                  }
                  type={typeof value === "number" ? "number" : "text"}
                />
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

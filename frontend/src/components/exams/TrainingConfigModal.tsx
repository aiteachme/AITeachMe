import type { ReactNode } from "react";
import { Info, RotateCcw, Save } from "lucide-react";

import { Button } from "../ui/Button";

export type QuestionCountMode = "preset" | "custom";

export interface QuestionCountPreset {
  label: string;
  value: number;
}

export function getQuestionCountMode(
  numQuestions: number,
  presets: readonly QuestionCountPreset[],
): QuestionCountMode {
  return presets.some((preset) => preset.value === numQuestions) ? "preset" : "custom";
}

export function TrainingConfigIntro({
  description,
}: {
  description: string;
}) {
  return (
    <div className="border-b border-slate-100 pb-3 dark:border-slate-800">
      <div className="flex items-start gap-2 text-xs leading-5 text-slate-500 dark:text-slate-400">
        <Info className="mt-0.5 h-4 w-4 shrink-0 text-slate-400 dark:text-slate-500" />
        <p>{description}</p>
      </div>
    </div>
  );
}

export function TrainingConfigField({
  label,
  description,
  children,
  align = "start",
}: {
  label: string;
  description?: string;
  children: ReactNode;
  align?: "start" | "center";
}) {
  return (
    <div
      className={`grid gap-2.5 py-4 sm:grid-cols-[7rem_minmax(0,1fr)] ${
        align === "center" ? "sm:items-center" : "sm:items-start"
      }`}
    >
      <div>
        <p className="text-sm font-bold text-slate-950 dark:text-slate-100">{label}</p>
        {description ? (
          <p className="mt-0.5 text-xs leading-4 text-slate-400 dark:text-slate-500">{description}</p>
        ) : null}
      </div>
      <div className="min-w-0">{children}</div>
    </div>
  );
}

export function QuestionCountSelector({
  value,
  mode,
  presets,
  min = 1,
  max = 80,
  customAriaLabel,
  onModeChange,
  onChange,
}: {
  value: number;
  mode: QuestionCountMode;
  presets: readonly QuestionCountPreset[];
  min?: number;
  max?: number;
  customAriaLabel: string;
  onModeChange: (mode: QuestionCountMode) => void;
  onChange: (value: number) => void;
}) {
  const isCustom = mode === "custom";
  return (
    <div className="space-y-2.5">
      <div className="grid grid-cols-2 gap-1 rounded-xl bg-slate-100 p-1 sm:grid-cols-4 dark:bg-slate-900">
        {presets.map((preset) => {
          const selected = !isCustom && value === preset.value;
          return (
            <button
              key={preset.value}
              type="button"
              onClick={() => {
                onModeChange("preset");
                onChange(preset.value);
              }}
              className={`min-h-10 rounded-lg px-2 py-1.5 text-center transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 ${
                selected
                  ? "bg-white text-slate-950 shadow-sm dark:bg-slate-800 dark:text-slate-100"
                  : "text-slate-500 hover:bg-white/70 hover:text-slate-950 dark:text-slate-400 dark:hover:bg-slate-800/70 dark:hover:text-slate-100"
              }`}
              aria-pressed={selected}
            >
              <span className="inline-flex items-baseline gap-1 text-sm font-bold">
                {preset.label}
                <span className="text-[11px] font-medium tabular-nums text-slate-400">{preset.value}题</span>
              </span>
            </button>
          );
        })}
        <button
          type="button"
          onClick={() => onModeChange("custom")}
          className={`min-h-10 rounded-lg px-2 py-1.5 text-center text-sm font-bold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 ${
            isCustom
              ? "bg-white text-slate-950 shadow-sm dark:bg-slate-800 dark:text-slate-100"
              : "text-slate-500 hover:bg-white/70 hover:text-slate-950 dark:text-slate-400 dark:hover:bg-slate-800/70 dark:hover:text-slate-100"
          }`}
          aria-pressed={isCustom}
        >
          自定义
        </button>
      </div>
      {isCustom ? (
        <label className="inline-flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400">
          <span>题量</span>
          <input
            className="h-9 w-24 rounded-lg border border-slate-200 bg-white px-3 text-center font-bold tabular-nums text-slate-950 outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-200 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:focus:border-slate-500 dark:focus:ring-slate-800"
            type="number"
            min={min}
            max={max}
            value={value}
            aria-label={customAriaLabel}
            onChange={(event) => onChange(Math.min(max, Math.max(min, Number(event.target.value) || min)))}
          />
          <span>题</span>
        </label>
      ) : null}
    </div>
  );
}

export interface ToggleOption {
  value: string;
  label: string;
  meta?: string;
}

export type OptionSelectionMode = "primary" | "custom";

export function OptionToggleGrid({
  primaryLabel,
  secondaryLabel = "指定题型",
  mode,
  options,
  selectedValues,
  emptyMessage,
  errorMessage,
  onModeChange,
  onToggle,
}: {
  primaryLabel: string;
  secondaryLabel?: string;
  mode: OptionSelectionMode;
  options: readonly ToggleOption[];
  selectedValues: ReadonlySet<string>;
  emptyMessage?: string;
  errorMessage?: string | null;
  onModeChange: (mode: OptionSelectionMode) => void;
  onToggle: (value: string) => void;
}) {
  if (!options.length) {
    return (
      <p className="rounded-xl border border-dashed border-slate-200 bg-slate-50 px-3 py-3 text-sm leading-6 text-slate-500 dark:border-slate-800 dark:bg-slate-900/40 dark:text-slate-400">
        {emptyMessage || "暂无可选项。"}
      </p>
    );
  }

  return (
    <div className="space-y-2.5">
      <div
        className="grid grid-cols-2 gap-1 rounded-xl bg-slate-100 p-1 dark:bg-slate-900"
        aria-label="题型方式"
        role="group"
      >
        {([
          { value: "primary" as const, label: primaryLabel },
          { value: "custom" as const, label: secondaryLabel },
        ]).map((item) => {
          const selected = mode === item.value;
          return (
            <button
              key={item.value}
              type="button"
              onClick={() => onModeChange(item.value)}
              className={`min-h-10 rounded-lg px-3 py-2 text-sm font-bold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 ${
                selected
                  ? "bg-white text-slate-950 shadow-sm dark:bg-slate-800 dark:text-slate-100"
                  : "text-slate-500 hover:bg-white/70 hover:text-slate-950 dark:text-slate-400 dark:hover:bg-slate-800/70 dark:hover:text-slate-100"
              }`}
              aria-pressed={selected}
            >
              {item.label}
            </button>
          );
        })}
      </div>
      {mode === "custom" ? (
        <>
          <div className="grid gap-2 sm:grid-cols-2">
            {options.map((option) => {
              const selected = selectedValues.has(option.value);
              return (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => onToggle(option.value)}
                  className={`flex min-h-10 items-center justify-between gap-3 rounded-xl border px-3.5 py-2 text-left text-sm transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 ${
                    selected
                      ? "border-slate-950 bg-slate-950 text-white dark:border-white dark:bg-white dark:text-slate-950"
                      : "border-slate-200 bg-white text-slate-600 hover:border-slate-400 hover:text-slate-950 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-300 dark:hover:border-slate-600 dark:hover:text-slate-100"
                  }`}
                  aria-pressed={selected}
                >
                  <span className="min-w-0 truncate font-bold">{option.label}</span>
                  {option.meta ? (
                    <span className={`shrink-0 text-xs ${selected ? "opacity-75" : "text-slate-400"}`}>
                      {option.meta}
                    </span>
                  ) : null}
                </button>
              );
            })}
          </div>
          {errorMessage ? <p className="text-xs font-semibold text-red-500">{errorMessage}</p> : null}
        </>
      ) : null}
    </div>
  );
}

export function TrainingConfigActions({
  onReset,
  onCancel,
  onSave,
  saveDisabled = false,
}: {
  onReset: () => void;
  onCancel: () => void;
  onSave: () => void;
  saveDisabled?: boolean;
}) {
  return (
    <div className="flex flex-col-reverse gap-2 border-t border-slate-100 pt-4 sm:flex-row sm:items-center sm:justify-between dark:border-slate-800">
      <Button variant="ghost" className="rounded-full px-4" onClick={onReset}>
        <RotateCcw className="h-4 w-4" />
        恢复默认
      </Button>
      <div className="grid grid-cols-2 gap-2 sm:flex">
        <Button variant="outline" className="rounded-full px-5" onClick={onCancel}>
          取消
        </Button>
        <Button
          className="rounded-full bg-black px-6 dark:bg-white dark:text-slate-950"
          onClick={onSave}
          disabled={saveDisabled}
        >
          <Save className="h-4 w-4" />
          保存配置
        </Button>
      </div>
    </div>
  );
}

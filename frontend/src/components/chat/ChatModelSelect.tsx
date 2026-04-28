import { useId } from "react";
import { SlidersHorizontal } from "lucide-react";

import { cn } from "../../lib/utils";

export type ChatModelChoice = "settings" | "deepseek-v4-flash" | "qwen3.6-flash";

export const DEFAULT_CHAT_MODEL_CHOICE: ChatModelChoice = "settings";

const CHAT_MODEL_OPTIONS: Array<{ value: ChatModelChoice; label: string }> = [
  { value: "settings", label: "使用设置" },
  { value: "deepseek-v4-flash", label: "DeepSeek V4 Flash" },
  { value: "qwen3.6-flash", label: "Qwen 3.6 Flash" },
];

export function toChatModelChoice(value: string | null | undefined): ChatModelChoice {
  if (value === "deepseek-v4-flash" || value === "qwen3.6-flash") {
    return value;
  }
  return DEFAULT_CHAT_MODEL_CHOICE;
}

export function toChatRequestModel(value: ChatModelChoice): string | undefined {
  return value === DEFAULT_CHAT_MODEL_CHOICE ? undefined : value;
}

interface ChatModelSelectProps {
  value: ChatModelChoice;
  onChange: (value: ChatModelChoice) => void;
  disabled?: boolean;
  className?: string;
}

export function ChatModelSelect({
  value,
  onChange,
  disabled = false,
  className,
}: ChatModelSelectProps) {
  const selectId = useId();

  return (
    <div
      className={cn(
        "inline-flex h-8 min-w-0 items-center gap-1.5 rounded-lg border border-zinc-200/80 bg-white/80 px-2 text-zinc-500 shadow-sm transition-colors focus-within:border-zinc-300 focus-within:ring-4 focus-within:ring-zinc-900/5 dark:border-slate-700/80 dark:bg-slate-900/80 dark:text-slate-400 dark:focus-within:border-slate-600 dark:focus-within:ring-slate-100/5",
        disabled && "opacity-60",
        className,
      )}
    >
      <SlidersHorizontal className="h-3.5 w-3.5 shrink-0" />
      <label htmlFor={selectId} className="sr-only">
        选择模型
      </label>
      <select
        id={selectId}
        value={value}
        onChange={(event) => onChange(toChatModelChoice(event.target.value))}
        disabled={disabled}
        className="h-full min-w-0 cursor-pointer bg-transparent text-[12px] font-medium text-zinc-600 outline-none disabled:cursor-not-allowed dark:text-slate-300"
      >
        {CHAT_MODEL_OPTIONS.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
}

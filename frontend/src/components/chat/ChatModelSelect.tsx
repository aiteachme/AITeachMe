import { useId } from "react";
import { ChevronDown, Cpu } from "lucide-react";

import { cn } from "../../lib/utils";

export type ChatModelChoice = "settings" | "deepseek-v4-flash" | "qwen3.6-flash" | "qwen-flash";

export const DEFAULT_CHAT_MODEL_CHOICE: ChatModelChoice = "settings";

const CHAT_MODEL_OPTIONS: Array<{ value: ChatModelChoice; label: string }> = [
  { value: "settings", label: "使用设置" },
  { value: "deepseek-v4-flash", label: "DeepSeek V4 Flash" },
  { value: "qwen3.6-flash", label: "Qwen 3.6 Flash" },
  { value: "qwen-flash", label: "Qwen Flash" },
];

export function toChatModelChoice(value: string | null | undefined): ChatModelChoice {
  if (value === "deepseek-v4-flash" || value === "qwen3.6-flash" || value === "qwen-flash") {
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
  const isUsingOverride = value !== DEFAULT_CHAT_MODEL_CHOICE;

  return (
    <div
      title="选择本轮模型"
      className={cn(
        "group relative inline-flex h-9 max-w-full shrink-0 items-center gap-2 rounded-full border px-3 text-[12px] font-medium shadow-sm transition-all",
        "focus-within:ring-4 focus-within:ring-zinc-900/5 dark:focus-within:ring-slate-100/5",
        isUsingOverride
          ? "border-indigo-200/90 bg-indigo-50 text-indigo-700 hover:border-indigo-300 hover:bg-indigo-50 dark:border-indigo-400/25 dark:bg-indigo-400/10 dark:text-indigo-200 dark:hover:border-indigo-300/30"
          : "border-zinc-200/80 bg-zinc-50/90 text-zinc-500 hover:border-zinc-300 hover:bg-white hover:text-zinc-700 dark:border-slate-700/70 dark:bg-slate-800/70 dark:text-slate-400 dark:hover:border-slate-600 dark:hover:bg-slate-800 dark:hover:text-slate-200",
        disabled && "opacity-55",
        className,
      )}
    >
      <Cpu className="h-3.5 w-3.5 shrink-0 opacity-80" />
      <label htmlFor={selectId} className="sr-only">
        选择模型
      </label>
      <span className="relative inline-flex min-w-0 items-center">
        <select
          id={selectId}
          value={value}
          onChange={(event) => onChange(toChatModelChoice(event.target.value))}
          disabled={disabled}
          aria-label="选择本轮模型"
          className="h-8 max-w-[150px] cursor-pointer appearance-none truncate bg-transparent pr-5 text-[12px] font-semibold leading-none text-current outline-none disabled:cursor-not-allowed sm:max-w-[176px]"
        >
          {CHAT_MODEL_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <ChevronDown className="pointer-events-none absolute right-0 h-3.5 w-3.5 text-current opacity-55 transition-opacity group-hover:opacity-80" />
      </span>
    </div>
  );
}

import { useId } from "react";
import { ChevronDown, Cpu } from "lucide-react";

import { cn } from "../../lib/utils";

export const CHAT_MODEL_OPTIONS = ["settings", "deepseek-v4-flash", "qwen-flash"] as const;

export type ChatModelChoice = (typeof CHAT_MODEL_OPTIONS)[number];

export const DEFAULT_CHAT_MODEL_CHOICE: ChatModelChoice = "settings";

const CHAT_MODEL_VALUES = new Set<string>(CHAT_MODEL_OPTIONS);

function getChatModelLabel(value: ChatModelChoice): string {
  return value === DEFAULT_CHAT_MODEL_CHOICE ? "使用设置" : value;
}

export function toChatModelChoice(value: string | null | undefined): ChatModelChoice {
  if (value && CHAT_MODEL_VALUES.has(value)) {
    return value as ChatModelChoice;
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
        "group relative inline-flex h-8 w-[156px] max-w-full shrink-0 items-center gap-1.5 rounded-lg border px-2 text-[12px] font-medium transition-all sm:w-[168px]",
        "shadow-[inset_0_1px_0_rgba(255,255,255,0.72)] focus-within:ring-2 focus-within:ring-zinc-900/5 dark:shadow-none dark:focus-within:ring-slate-100/5",
        isUsingOverride
          ? "border-sky-200/90 bg-sky-50/80 text-sky-700 hover:border-sky-300 hover:bg-sky-50 dark:border-sky-400/25 dark:bg-sky-400/10 dark:text-sky-200 dark:hover:border-sky-300/30"
          : "border-zinc-200/80 bg-white/55 text-zinc-500 hover:border-zinc-300 hover:bg-white hover:text-zinc-700 dark:border-slate-700/70 dark:bg-slate-900/45 dark:text-slate-400 dark:hover:border-slate-600 dark:hover:bg-slate-800 dark:hover:text-slate-200",
        disabled && "opacity-55",
        className,
      )}
    >
      <span
        className={cn(
          "flex h-5 w-5 shrink-0 items-center justify-center rounded-md transition-colors",
          isUsingOverride
            ? "bg-sky-100 text-sky-700 dark:bg-sky-400/15 dark:text-sky-200"
            : "bg-zinc-100 text-zinc-500 group-hover:bg-zinc-200/70 group-hover:text-zinc-700 dark:bg-slate-800 dark:text-slate-400 dark:group-hover:bg-slate-700 dark:group-hover:text-slate-200",
        )}
      >
        <Cpu className="h-3.5 w-3.5" />
      </span>
      <label htmlFor={selectId} className="sr-only">
        选择模型
      </label>
      <span className="relative inline-flex min-w-0 flex-1 items-center">
        <select
          id={selectId}
          value={value}
          onChange={(event) => onChange(toChatModelChoice(event.target.value))}
          disabled={disabled}
          aria-label="选择本轮模型"
          className="h-7 w-full min-w-0 cursor-pointer appearance-none truncate bg-transparent pr-4 text-[12px] font-medium leading-none text-current outline-none disabled:cursor-not-allowed"
        >
          {CHAT_MODEL_OPTIONS.map((option) => (
            <option key={option} value={option}>
              {getChatModelLabel(option)}
            </option>
          ))}
        </select>
        <ChevronDown className="pointer-events-none absolute right-0 h-3.5 w-3.5 text-current opacity-55 transition-opacity group-hover:opacity-80" />
      </span>
    </div>
  );
}

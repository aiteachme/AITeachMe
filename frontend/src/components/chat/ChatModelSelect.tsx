import { useId } from "react";
import { ChevronDown, Sparkles } from "lucide-react";

import { cn } from "../../lib/utils";

export const CHAT_MODEL_OPTIONS = ["settings", "qwen-flash", "deepseek-v4-flash"] as const;

export type ChatModelChoice = (typeof CHAT_MODEL_OPTIONS)[number];

export const DEFAULT_CHAT_MODEL_CHOICE: ChatModelChoice = "settings";

const CHAT_MODEL_VALUES = new Set<string>(CHAT_MODEL_OPTIONS);

const CHAT_MODEL_META: Record<ChatModelChoice, {
  optionLabel: string;
  displayLabel: string;
  title: string;
}> = {
  settings: {
    optionLabel: "默认模式",
    displayLabel: "",
    title: "默认模式",
  },
  "qwen-flash": {
    optionLabel: "qwen-flash",
    displayLabel: "qwen-flash",
    title: "切换到 qwen-flash",
  },
  "deepseek-v4-flash": {
    optionLabel: "deepseek-v4-flash",
    displayLabel: "deepseek-v4-flash",
    title: "切换到 deepseek-v4-flash",
  },
};

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
  const meta = CHAT_MODEL_META[value];

  return (
    <div
      title={`选择本轮模型：${meta.title}`}
      className={cn(
        "group relative inline-flex h-9 max-w-full shrink-0 items-center overflow-hidden rounded-full border text-xs font-semibold transition-all",
        "shadow-[inset_0_1px_0_rgba(255,255,255,0.78),0_8px_18px_-14px_rgba(79,70,229,0.55)] focus-within:ring-4 focus-within:ring-indigo-500/10 dark:shadow-none",
        isUsingOverride
          ? "w-9 justify-center border-indigo-200/80 bg-indigo-50/90 text-indigo-700 hover:border-indigo-300 hover:bg-indigo-100/80 dark:border-indigo-400/25 dark:bg-indigo-400/15 dark:text-indigo-100 dark:hover:border-indigo-300/35 sm:min-w-[132px] sm:max-w-[180px] sm:justify-start sm:gap-2 sm:bg-white/80 sm:px-2.5 sm:pr-3 sm:hover:bg-indigo-50/80 dark:sm:bg-indigo-400/10 dark:sm:hover:bg-indigo-400/15"
          : "w-9 justify-center border-indigo-200/80 bg-indigo-50/90 text-indigo-700 hover:border-indigo-300 hover:bg-indigo-100/80 dark:border-indigo-400/30 dark:bg-indigo-400/15 dark:text-indigo-100 dark:hover:border-indigo-300/35",
        disabled && "opacity-55",
        className,
      )}
    >
      <span
        className={cn(
          "flex shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-indigo-500 via-violet-500 to-fuchsia-500 text-white shadow-sm shadow-indigo-500/25 transition-transform group-hover:scale-[1.03]",
          isUsingOverride
            ? "h-7 w-7 sm:h-6 sm:w-6"
            : "h-7 w-7",
        )}
      >
        <Sparkles className={cn(isUsingOverride ? "h-3.5 w-3.5" : "h-4 w-4")} />
      </span>
      <label htmlFor={selectId} className="sr-only">
        选择模型
      </label>
      {isUsingOverride ? (
        <>
          <span className="hidden min-w-0 truncate leading-none sm:inline">{meta.displayLabel}</span>
          <ChevronDown className="hidden h-3.5 w-3.5 shrink-0 opacity-55 transition-opacity group-hover:opacity-80 sm:block" />
        </>
      ) : null}
      <select
        id={selectId}
        value={value}
        onChange={(event) => onChange(toChatModelChoice(event.target.value))}
        disabled={disabled}
        aria-label="选择本轮模型"
        className="absolute inset-0 h-full w-full cursor-pointer opacity-0 disabled:cursor-not-allowed"
      >
        {CHAT_MODEL_OPTIONS.map((option) => (
          <option
            key={option}
            value={option}
            className="bg-white text-zinc-900 dark:bg-slate-950 dark:text-slate-100"
            style={{ backgroundColor: "#ffffff", color: "#18181b" }}
          >
            {CHAT_MODEL_META[option].optionLabel}
          </option>
        ))}
      </select>
    </div>
  );
}

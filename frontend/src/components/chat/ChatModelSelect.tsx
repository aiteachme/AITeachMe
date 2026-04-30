import { useId } from "react";
import { ChevronDown, Settings2 } from "lucide-react";

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
    displayLabel: "使用设置",
    title: "使用设置",
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
  const meta = CHAT_MODEL_META[value];

  return (
    <div
      title={`选择本轮模型：${meta.title}`}
      className={cn(
        "group relative inline-flex h-9 min-w-[132px] max-w-[176px] shrink-0 items-center gap-1.5 overflow-hidden rounded-full border px-3 text-[13px] font-medium transition-all",
        "border-zinc-200/70 bg-gradient-to-b from-white to-zinc-50/95 text-zinc-500 shadow-[inset_0_1px_0_rgba(255,255,255,0.95),0_8px_20px_-18px_rgba(24,24,27,0.5)]",
        "hover:border-zinc-300/80 hover:from-white hover:to-zinc-100 hover:text-zinc-700 hover:shadow-[inset_0_1px_0_rgba(255,255,255,0.98),0_10px_22px_-18px_rgba(24,24,27,0.6)]",
        "focus-within:outline-none focus-within:ring-4 focus-within:ring-zinc-900/10 dark:border-slate-700/70 dark:from-slate-800 dark:to-slate-900/90 dark:text-slate-300 dark:shadow-none dark:hover:border-slate-600 dark:hover:from-slate-800 dark:hover:to-slate-800 dark:hover:text-slate-100 dark:focus-within:ring-slate-100/10",
        disabled && "opacity-55",
        className,
      )}
    >
      <Settings2 className="h-4 w-4 shrink-0 text-zinc-500 transition-colors group-hover:text-zinc-700 dark:text-slate-400 dark:group-hover:text-slate-200" />
      <label htmlFor={selectId} className="sr-only">
        选择模型
      </label>
      <span className="min-w-0 truncate leading-none">{meta.displayLabel}</span>
      <ChevronDown className="h-3.5 w-3.5 shrink-0 opacity-45 transition-opacity group-hover:opacity-70" />
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

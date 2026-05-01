import { useId } from "react";
import { Bot, ChevronDown } from "lucide-react";

import { cn } from "../../lib/utils";

export const CHAT_MODEL_OPTIONS = ["settings", "deepseek-v4-flash", "qwen-flash"] as const;

export type ChatModelChoice = (typeof CHAT_MODEL_OPTIONS)[number];

export const DEFAULT_CHAT_MODEL_CHOICE: ChatModelChoice = "settings";

const CHAT_MODEL_VALUES = new Set<string>(CHAT_MODEL_OPTIONS);

const CHAT_MODEL_META: Record<ChatModelChoice, {
  optionLabel: string;
  displayLabel: string;
  caption: string;
  title: string;
}> = {
  settings: {
    optionLabel: "默认",
    displayLabel: "默认",
    caption: "跟随系统",
    title: "使用系统设置中的默认模型",
  },
  "deepseek-v4-flash": {
    optionLabel: "deepseek-v4-flash",
    displayLabel: "deepseek-v4-flash",
    caption: "极速推理",
    title: "切换到 deepseek-v4-flash",
  },
  "qwen-flash": {
    optionLabel: "qwen-flash",
    displayLabel: "qwen-flash",
    caption: "均衡快答",
    title: "切换到 qwen-flash",
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
  const descriptionId = `${selectId}-description`;
  const meta = CHAT_MODEL_META[value];

  return (
    <div
      title={`选择本轮模型：${meta.title}`}
      className={cn(
        "group relative inline-flex h-11 max-w-full items-center gap-2.5 overflow-hidden rounded-2xl border px-3 text-left transition-all",
        "border-zinc-200/80 bg-white/92 text-zinc-700 shadow-[0_1px_2px_rgba(24,24,27,0.04),inset_0_1px_0_rgba(255,255,255,0.88)] hover:border-zinc-300 hover:bg-white hover:text-zinc-950",
        "focus-within:outline-none focus-within:ring-4 focus-within:ring-zinc-900/10 dark:border-slate-700/75 dark:bg-slate-900/86 dark:text-slate-200 dark:shadow-none dark:hover:border-slate-600 dark:hover:bg-slate-900 dark:hover:text-slate-50 dark:focus-within:ring-slate-100/10",
        disabled && "cursor-not-allowed opacity-55",
        className,
        "min-w-[172px]",
      )}
    >
      <Bot className="h-4 w-4 shrink-0 text-zinc-500 transition-colors group-hover:text-zinc-800 dark:text-slate-400 dark:group-hover:text-slate-100" />
      <label htmlFor={selectId} className="sr-only">
        选择模型
      </label>
      <span className="flex min-w-0 flex-1 flex-col justify-center">
        <span className="truncate text-[13px] font-semibold leading-4">{meta.displayLabel}</span>
        <span id={descriptionId} className="mt-0.5 hidden truncate text-[11px] font-medium leading-3 text-zinc-400 dark:text-slate-500 md:block">
          {meta.caption}
        </span>
      </span>
      <ChevronDown className="h-3.5 w-3.5 shrink-0 text-zinc-400 transition-colors group-hover:text-zinc-700 dark:text-slate-500 dark:group-hover:text-slate-200" />
      <select
        id={selectId}
        value={value}
        onChange={(event) => onChange(toChatModelChoice(event.target.value))}
        disabled={disabled}
        aria-label="选择本轮模型"
        aria-describedby={descriptionId}
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

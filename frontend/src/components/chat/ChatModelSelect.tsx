import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type CSSProperties,
  type KeyboardEvent,
} from "react";
import { createPortal } from "react-dom";
import { Check, ChevronDown, Network } from "lucide-react";

import { cn } from "../../lib/utils";

export const CHAT_MODEL_OPTIONS = [
  "settings",
  "gpt-5.5",
  "gpt-5.4",
  "gpt-5.4-mini",
  "gpt-5.2",
  "gpt-5.3-codex",
  "gemini-3.1-flash-lite",
] as const;

export type ChatModelChoice = (typeof CHAT_MODEL_OPTIONS)[number];

export const DEFAULT_CHAT_MODEL_CHOICE: ChatModelChoice = "settings";

const CHAT_MODEL_VALUES = new Set<string>(CHAT_MODEL_OPTIONS);
const CHAT_MODEL_STORAGE_KEY = "aiteachme:global-chat-model";
const CHAT_MODEL_CHANGED_EVENT = "aiteachme:global-chat-model-changed";

const CHAT_MODEL_META: Record<ChatModelChoice, {
  optionLabel: string;
  triggerLabel: string;
  menuLabel: string;
  caption: string;
  title: string;
}> = {
  settings: {
    optionLabel: "默认",
    triggerLabel: "默认",
    menuLabel: "默认",
    caption: "使用设置页的主文本模型",
    title: "使用设置页中配置的主文本模型",
  },
  "gpt-5.5": {
    optionLabel: "深度推理",
    triggerLabel: "深度推理",
    menuLabel: "深度推理",
    caption: "复杂规划 · 深入讲解",
    title: "适合复杂推理、规划和讲解",
  },
  "gpt-5.4": {
    optionLabel: "高质量",
    triggerLabel: "高质量",
    menuLabel: "高质量",
    caption: "高质量生成 · 复杂任务",
    title: "适合高质量生成和复杂课程构建",
  },
  "gpt-5.4-mini": {
    optionLabel: "均衡",
    triggerLabel: "均衡",
    menuLabel: "均衡",
    caption: "稳定生成 · 日常问答",
    title: "适合快速规划、生成和问答",
  },
  "gpt-5.2": {
    optionLabel: "标准",
    triggerLabel: "标准",
    menuLabel: "标准",
    caption: "常规生成 · 稳定问答",
    title: "适合常规生成、批改和问答",
  },
  "gpt-5.3-codex": {
    optionLabel: "代码",
    triggerLabel: "代码",
    menuLabel: "代码",
    caption: "代码任务 · 结构化修改",
    title: "适合代码相关解释和修改",
  },
  "gemini-3.1-flash-lite": {
    optionLabel: "快速响应",
    triggerLabel: "快速响应",
    menuLabel: "快速响应",
    caption: "轻量问答 · 快速响应",
    title: "适合轻量问答和快速响应",
  },
};

export function toChatModelChoice(value: string | null | undefined): ChatModelChoice {
  if (value && CHAT_MODEL_VALUES.has(value)) {
    return value as ChatModelChoice;
  }
  return DEFAULT_CHAT_MODEL_CHOICE;
}

export function toChatRequestModel(value: ChatModelChoice): string {
  return value;
}

function readStoredChatModelChoice(): ChatModelChoice {
  if (typeof window === "undefined") {
    return DEFAULT_CHAT_MODEL_CHOICE;
  }
  return toChatModelChoice(window.localStorage.getItem(CHAT_MODEL_STORAGE_KEY));
}

function subscribeChatModelChoice(onStoreChange: () => void): () => void {
  if (typeof window === "undefined") {
    return () => {};
  }

  const handleStorage = (event: StorageEvent) => {
    if (event.key === CHAT_MODEL_STORAGE_KEY) {
      onStoreChange();
    }
  };
  window.addEventListener(CHAT_MODEL_CHANGED_EVENT, onStoreChange);
  window.addEventListener("storage", handleStorage);
  return () => {
    window.removeEventListener(CHAT_MODEL_CHANGED_EVENT, onStoreChange);
    window.removeEventListener("storage", handleStorage);
  };
}

export function useGlobalChatModelChoice(): [ChatModelChoice, (value: ChatModelChoice) => void] {
  const value = useSyncExternalStore(
    subscribeChatModelChoice,
    readStoredChatModelChoice,
    () => DEFAULT_CHAT_MODEL_CHOICE,
  );
  const setValue = useCallback((nextValue: ChatModelChoice) => {
    if (typeof window === "undefined") {
      return;
    }
    window.localStorage.setItem(CHAT_MODEL_STORAGE_KEY, nextValue);
    window.dispatchEvent(new Event(CHAT_MODEL_CHANGED_EVENT));
  }, []);
  return [value, setValue];
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
  const generatedId = useId();
  const triggerId = `chat-model-select-${generatedId}`;
  const listboxId = `${triggerId}-listbox`;
  const descriptionId = `${triggerId}-description`;
  const rootRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const [highlightedValue, setHighlightedValue] = useState<ChatModelChoice>(value);
  const [menuStyle, setMenuStyle] = useState<CSSProperties>();
  const meta = CHAT_MODEL_META[value];

  const updateMenuPosition = () => {
    const triggerRect = triggerRef.current?.getBoundingClientRect();
    if (!triggerRect) return;

    const viewportMargin = 12;
    const gap = 8;
    const preferredWidth = 320;
    const preferredMaxHeight = 260;
    const minHeight = 128;
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;
    const spaceBelow = viewportHeight - triggerRect.bottom - viewportMargin;
    const spaceAbove = triggerRect.top - viewportMargin;
    const openAbove = spaceBelow < minHeight && spaceAbove > spaceBelow;
    const availableHeight = Math.max(minHeight, openAbove ? spaceAbove : spaceBelow);
    const maxHeight = Math.min(preferredMaxHeight, Math.max(minHeight, availableHeight - gap));
    const width = Math.min(
      Math.max(preferredWidth, triggerRect.width),
      viewportWidth - viewportMargin * 2,
    );
    const left = Math.min(
      Math.max(viewportMargin, triggerRect.right - width),
      viewportWidth - viewportMargin - width,
    );
    const top = openAbove
      ? Math.max(viewportMargin, triggerRect.top - maxHeight - gap)
      : Math.min(triggerRect.bottom + gap, viewportHeight - viewportMargin - maxHeight);

    setMenuStyle({
      left,
      maxHeight,
      position: "fixed",
      top,
      width,
    });
  };

  useLayoutEffect(() => {
    if (!open) return;

    updateMenuPosition();
    window.addEventListener("resize", updateMenuPosition);
    window.addEventListener("scroll", updateMenuPosition, true);
    return () => {
      window.removeEventListener("resize", updateMenuPosition);
      window.removeEventListener("scroll", updateMenuPosition, true);
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;

    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (rootRef.current?.contains(target) || menuRef.current?.contains(target)) return;
      setOpen(false);
    };

    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [open]);

  useEffect(() => {
    if (open) {
      setHighlightedValue(value);
    }
  }, [open, value]);

  useEffect(() => {
    if (disabled) {
      setOpen(false);
    }
  }, [disabled]);

  const selectValue = (nextValue: ChatModelChoice) => {
    onChange(nextValue);
    setOpen(false);
    requestAnimationFrame(() => triggerRef.current?.focus({ preventScroll: true }));
  };

  const moveHighlight = (direction: 1 | -1) => {
    const currentIndex = Math.max(
      0,
      CHAT_MODEL_OPTIONS.findIndex((option) => option === highlightedValue),
    );
    const nextIndex = (currentIndex + direction + CHAT_MODEL_OPTIONS.length) % CHAT_MODEL_OPTIONS.length;
    setHighlightedValue(CHAT_MODEL_OPTIONS[nextIndex]);
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (disabled) return;

    if (event.key === "Escape") {
      setOpen(false);
      triggerRef.current?.focus({ preventScroll: true });
      return;
    }

    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!open) {
        setOpen(true);
        setHighlightedValue(value);
        return;
      }
      moveHighlight(event.key === "ArrowDown" ? 1 : -1);
      return;
    }

    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      if (!open) {
        setOpen(true);
        setHighlightedValue(value);
        return;
      }
      selectValue(highlightedValue);
    }
  };

  const menu = open ? (
    <div
      ref={menuRef}
      id={listboxId}
      role="listbox"
      aria-labelledby={triggerId}
      className="z-[140] max-h-64 overflow-y-auto rounded-2xl border border-zinc-200/90 bg-white/95 p-1.5 shadow-[0_18px_48px_-22px_rgba(24,24,27,0.35),0_8px_18px_-12px_rgba(24,24,27,0.24)] backdrop-blur-xl dark:border-slate-700/80 dark:bg-slate-900/95 dark:shadow-black/40"
      style={menuStyle}
    >
      {CHAT_MODEL_OPTIONS.map((option) => {
        const optionMeta = CHAT_MODEL_META[option];
        const selected = option === value;
        const highlighted = option === highlightedValue;
        return (
          <button
            key={option}
            type="button"
            id={`${listboxId}-${option}`}
            role="option"
            aria-selected={selected}
            onMouseEnter={() => setHighlightedValue(option)}
            onClick={() => selectValue(option)}
            className={cn(
              "group/option flex min-h-12 w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left transition-colors",
              highlighted
                ? "bg-zinc-100 text-zinc-950 dark:bg-slate-800 dark:text-slate-50"
                : "text-zinc-700 hover:bg-zinc-50 hover:text-zinc-950 dark:text-slate-200 dark:hover:bg-slate-800/80 dark:hover:text-slate-50",
              selected && option === DEFAULT_CHAT_MODEL_CHOICE && "font-semibold",
              selected && option !== DEFAULT_CHAT_MODEL_CHOICE && "bg-violet-50 font-semibold text-violet-950 hover:bg-violet-50 dark:bg-violet-500/15 dark:text-violet-50 dark:hover:bg-violet-500/15",
            )}
          >
            <span
              className={cn(
                "flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border transition-colors",
                selected && option === DEFAULT_CHAT_MODEL_CHOICE
                  ? "border-zinc-900 bg-zinc-900 text-white dark:border-slate-100 dark:bg-slate-100 dark:text-slate-900"
                  : selected
                  ? "border-violet-600 bg-violet-600 text-white dark:border-violet-300 dark:bg-violet-300 dark:text-violet-950"
                  : "border-zinc-200 bg-white text-zinc-500 group-hover/option:border-zinc-300 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-400 dark:group-hover/option:border-slate-600",
              )}
              aria-hidden="true"
            >
              <Network className="h-3.5 w-3.5" />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[13px] leading-4">{optionMeta.menuLabel}</span>
              <span
                className={cn(
                  "mt-0.5 block text-[11px] font-medium leading-4",
                  selected && option !== DEFAULT_CHAT_MODEL_CHOICE
                    ? "text-violet-700 dark:text-violet-200"
                    : "text-zinc-500 dark:text-slate-400",
                )}
              >
                {optionMeta.caption}
              </span>
            </span>
            {selected ? <Check className="h-4 w-4 shrink-0" aria-hidden="true" /> : null}
          </button>
        );
      })}
    </div>
  ) : null;

  return (
    <>
      <div
        ref={rootRef}
        title={`选择生成模型：${meta.title}`}
        onKeyDown={handleKeyDown}
        className={cn(
          "relative inline-flex h-7 w-auto min-w-0 max-w-full",
          disabled && "cursor-not-allowed opacity-55",
          className,
        )}
      >
        <button
          ref={triggerRef}
          id={triggerId}
          type="button"
          disabled={disabled}
          aria-haspopup="listbox"
          aria-expanded={open}
          aria-controls={listboxId}
          aria-describedby={descriptionId}
          aria-label={`选择生成模型，当前为${meta.optionLabel}`}
          onClick={() => {
            if (!disabled) {
              setOpen((current) => !current);
            }
          }}
          className={cn(
            "group inline-flex h-full w-auto max-w-[128px] items-center gap-1.5 rounded-md px-1.5 text-left text-[12px] font-medium leading-none text-zinc-500 transition-colors active:scale-[0.98]",
            "hover:bg-zinc-100/70 hover:text-zinc-800 focus:outline-none focus:ring-2 focus:ring-zinc-900/10 dark:text-slate-400 dark:hover:bg-slate-800/70 dark:hover:text-slate-100 dark:focus:ring-slate-100/10",
            open && "bg-zinc-100/80 text-zinc-800 dark:bg-slate-800 dark:text-slate-100",
            disabled && "cursor-not-allowed active:scale-100",
          )}
        >
          <Network
            className="h-3.5 w-3.5 shrink-0 text-zinc-500 transition-colors group-hover:text-zinc-700 dark:text-slate-400 dark:group-hover:text-slate-100"
            aria-hidden="true"
          />
          <span className="inline-flex min-w-0 items-baseline">
            <span className="truncate font-semibold text-zinc-700 dark:text-slate-200">{meta.triggerLabel}</span>
            <span id={descriptionId} className="sr-only">
              {meta.caption}
            </span>
          </span>
          <ChevronDown
            className={cn(
              "h-3 w-3 shrink-0 text-zinc-400 transition-all group-hover:text-zinc-600 dark:text-slate-500 dark:group-hover:text-slate-200",
              open && "rotate-180 text-zinc-600 dark:text-slate-200",
            )}
            aria-hidden="true"
          />
        </button>
      </div>
      {menu && typeof document !== "undefined" ? createPortal(menu, document.body) : null}
    </>
  );
}

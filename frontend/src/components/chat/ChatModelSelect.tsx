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
  "reason",
  "primary",
  "light",
] as const;

export type ChatModelChoice = (typeof CHAT_MODEL_OPTIONS)[number];

export const DEFAULT_CHAT_MODEL_CHOICE: ChatModelChoice = "settings";

const CHAT_MODEL_VALUES = new Set<string>(CHAT_MODEL_OPTIONS);
const CHAT_MODEL_CHANGED_EVENT = "aiteachme:global-chat-model-changed";
let currentChatModelChoice: ChatModelChoice = DEFAULT_CHAT_MODEL_CHOICE;

export interface ChatModelBuildEstimate {
  shortLabel: string;
}

const CHAT_MODEL_META: Record<ChatModelChoice, {
  optionLabel: string;
  triggerLabel: string;
  menuLabel: string;
  caption: string;
  title: string;
  buildEstimate: ChatModelBuildEstimate;
}> = {
  settings: {
    optionLabel: "自动",
    triggerLabel: "自动",
    menuLabel: "自动",
    caption: "按设置页的模型分层自动选择",
    title: "保留各工作流的模型分层策略",
    buildEstimate: {
      shortLabel: "5-10分钟",
    },
  },
  reason: {
    optionLabel: "深度推理",
    triggerLabel: "深度推理",
    menuLabel: "深度推理",
    caption: "复杂规划 · 深入讲解",
    title: "适合复杂推理、规划和讲解",
    buildEstimate: {
      shortLabel: "8-15分钟",
    },
  },
  primary: {
    optionLabel: "均衡",
    triggerLabel: "均衡",
    menuLabel: "均衡",
    caption: "稳定生成 · 日常问答",
    title: "适合快速规划、生成和问答",
    buildEstimate: {
      shortLabel: "5-10分钟",
    },
  },
  light: {
    optionLabel: "快速",
    triggerLabel: "快速",
    menuLabel: "快速",
    caption: "轻量问答 · 快速响应",
    title: "适合轻量问答和快速响应",
    buildEstimate: {
      shortLabel: "4-8分钟",
    },
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

export function getChatModelBuildEstimate(value: ChatModelChoice): ChatModelBuildEstimate {
  return CHAT_MODEL_META[toChatModelChoice(value)].buildEstimate;
}

function readStoredChatModelChoice(): ChatModelChoice {
  return currentChatModelChoice;
}

function subscribeChatModelChoice(onStoreChange: () => void): () => void {
  if (typeof window === "undefined") {
    return () => {};
  }
  window.addEventListener(CHAT_MODEL_CHANGED_EVENT, onStoreChange);
  return () => {
    window.removeEventListener(CHAT_MODEL_CHANGED_EVENT, onStoreChange);
  };
}

export function useGlobalChatModelChoice(): [ChatModelChoice, (value: ChatModelChoice) => void] {
  const value = useSyncExternalStore(
    subscribeChatModelChoice,
    readStoredChatModelChoice,
    () => DEFAULT_CHAT_MODEL_CHOICE,
  );
  const setValue = useCallback((nextValue: ChatModelChoice) => {
    currentChatModelChoice = toChatModelChoice(nextValue);
    if (typeof window !== "undefined") {
      window.dispatchEvent(new Event(CHAT_MODEL_CHANGED_EVENT));
    }
  }, []);
  return [value, setValue];
}

interface ChatModelSelectProps {
  value: ChatModelChoice;
  onChange: (value: ChatModelChoice) => void;
  disabled?: boolean;
  className?: string;
  showBuildEstimate?: boolean;
}

export function ChatModelSelect({
  value,
  onChange,
  disabled = false,
  className,
  showBuildEstimate = false,
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
      data-ai-interaction-portal="true"
      className="z-[12000] max-h-64 overflow-y-auto rounded-2xl border border-zinc-200/90 bg-white/95 p-1.5 shadow-[0_18px_48px_-22px_rgba(24,24,27,0.35),0_8px_18px_-12px_rgba(24,24,27,0.24)] backdrop-blur-xl dark:border-slate-700/80 dark:bg-slate-900/95 dark:shadow-black/40"
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
            {showBuildEstimate ? (
              <span
                className={cn(
                  "shrink-0 self-start pt-0.5 text-[11px] font-semibold tabular-nums",
                  selected && option !== DEFAULT_CHAT_MODEL_CHOICE
                    ? "text-violet-700 dark:text-violet-200"
                    : "text-zinc-400 dark:text-slate-500",
                )}
                title={`预计构建时间约 ${optionMeta.buildEstimate.shortLabel}`}
              >
                {optionMeta.buildEstimate.shortLabel}
              </span>
            ) : null}
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
        title={showBuildEstimate ? `选择生成模型：${meta.title}。预计构建时间约 ${meta.buildEstimate.shortLabel}` : `选择生成模型：${meta.title}`}
        onKeyDown={handleKeyDown}
        className={cn(
          "relative inline-flex w-auto min-w-0 max-w-full",
          "h-7",
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
            "group inline-flex h-full w-auto items-center gap-1.5 rounded-md px-1.5 text-left text-[12px] font-medium leading-none text-zinc-500 transition-colors active:scale-[0.98]",
            showBuildEstimate ? "max-w-[138px]" : "max-w-[128px]",
            "hover:bg-zinc-100/70 hover:text-zinc-800 focus:outline-none focus:ring-2 focus:ring-zinc-900/10 dark:text-slate-400 dark:hover:bg-slate-800/70 dark:hover:text-slate-100 dark:focus:ring-slate-100/10",
            open && "bg-zinc-100/80 text-zinc-800 dark:bg-slate-800 dark:text-slate-100",
            disabled && "cursor-not-allowed active:scale-100",
          )}
        >
          <Network
            className="h-3.5 w-3.5 shrink-0 text-zinc-500 transition-colors group-hover:text-zinc-700 dark:text-slate-400 dark:group-hover:text-slate-100"
            aria-hidden="true"
          />
          <span className="inline-flex min-w-0 items-baseline gap-1">
            <span className="truncate font-semibold text-zinc-700 dark:text-slate-200">{meta.triggerLabel}</span>
            {showBuildEstimate ? (
              <span
                className="truncate text-[10.5px] font-semibold tabular-nums text-zinc-400 dark:text-slate-500"
                aria-hidden="true"
              >
                {meta.buildEstimate.shortLabel}
              </span>
            ) : null}
            <span id={descriptionId} className="sr-only">
              {showBuildEstimate ? `${meta.caption}，预计构建时间约${meta.buildEstimate.shortLabel}` : meta.caption}
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

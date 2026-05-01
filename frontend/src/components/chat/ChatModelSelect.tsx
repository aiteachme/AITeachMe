import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
} from "react";
import { createPortal } from "react-dom";
import { Bot, Check, ChevronDown } from "lucide-react";

import { cn } from "../../lib/utils";

export const CHAT_MODEL_OPTIONS = ["settings", "deepseek-v4-flash", "qwen-flash"] as const;

export type ChatModelChoice = (typeof CHAT_MODEL_OPTIONS)[number];

export const DEFAULT_CHAT_MODEL_CHOICE: ChatModelChoice = "settings";

const CHAT_MODEL_VALUES = new Set<string>(CHAT_MODEL_OPTIONS);

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
    menuLabel: "默认模型",
    caption: "跟随系统设置",
    title: "使用系统设置中的默认模型",
  },
  "deepseek-v4-flash": {
    optionLabel: "deepseek-v4-flash",
    triggerLabel: "DeepSeek",
    menuLabel: "DeepSeek V4 Flash",
    caption: "更强推理 · 讲解更稳",
    title: "切换到 deepseek-v4-flash，适合更稳的推理和讲解",
  },
  "qwen-flash": {
    optionLabel: "qwen-flash",
    triggerLabel: "Qwen",
    menuLabel: "Qwen Flash",
    caption: "更快响应 · 轻量问答",
    title: "切换到 qwen-flash，适合最快响应和轻量问答",
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
  const isExplicitModel = value !== DEFAULT_CHAT_MODEL_CHOICE;

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
              <Bot className="h-3.5 w-3.5" />
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
        title={`选择本轮模型：${meta.title}`}
        onKeyDown={handleKeyDown}
        className={cn(
          "relative inline-flex h-9 min-w-[118px] max-w-full",
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
          aria-label={`选择本轮模型，当前为${meta.optionLabel}`}
          onClick={() => {
            if (!disabled) {
              setOpen((current) => !current);
            }
          }}
          className={cn(
            "group inline-flex h-full w-full items-center gap-2 rounded-xl border px-2.5 text-left transition-all active:scale-[0.98]",
            "border-zinc-200/80 bg-white/92 text-zinc-700 shadow-[0_1px_2px_rgba(24,24,27,0.04),inset_0_1px_0_rgba(255,255,255,0.88)] hover:border-zinc-300 hover:bg-white hover:text-zinc-950",
            "focus:outline-none focus:ring-4 focus:ring-zinc-900/10 dark:border-slate-700/75 dark:bg-slate-900/86 dark:text-slate-200 dark:shadow-none dark:hover:border-slate-600 dark:hover:bg-slate-900 dark:hover:text-slate-50 dark:focus:ring-slate-100/10",
            isExplicitModel && "border-violet-200 bg-violet-50/85 text-violet-950 shadow-[0_1px_2px_rgba(109,40,217,0.08),inset_0_1px_0_rgba(255,255,255,0.88)] hover:border-violet-300 hover:bg-violet-50 hover:text-violet-950 focus:ring-violet-500/15 dark:border-violet-400/35 dark:bg-violet-500/15 dark:text-violet-50 dark:hover:border-violet-300/60 dark:hover:bg-violet-500/20 dark:focus:ring-violet-300/15",
            open && "border-zinc-400 bg-white text-zinc-950 ring-4 ring-zinc-900/10 dark:border-slate-500 dark:bg-slate-900 dark:text-slate-50 dark:ring-slate-100/10",
            open && isExplicitModel && "border-violet-400 bg-violet-50 text-violet-950 ring-violet-500/15 dark:border-violet-300/70 dark:bg-violet-500/20 dark:text-violet-50 dark:ring-violet-300/15",
            disabled && "cursor-not-allowed active:scale-100",
          )}
        >
          <Bot
            className={cn(
              "h-4 w-4 shrink-0 transition-colors",
              isExplicitModel
                ? "text-violet-600 group-hover:text-violet-700 dark:text-violet-200 dark:group-hover:text-violet-100"
                : "text-zinc-500 group-hover:text-zinc-800 dark:text-slate-400 dark:group-hover:text-slate-100",
            )}
            aria-hidden="true"
          />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-[13px] font-semibold leading-none">{meta.triggerLabel}</span>
            <span id={descriptionId} className="sr-only">
              {meta.caption}
            </span>
          </span>
          <ChevronDown
            className={cn(
              "h-3.5 w-3.5 shrink-0 text-zinc-400 transition-all group-hover:text-zinc-700 dark:text-slate-500 dark:group-hover:text-slate-200",
              isExplicitModel && "text-violet-500 group-hover:text-violet-700 dark:text-violet-200 dark:group-hover:text-violet-100",
              open && "rotate-180 text-zinc-700 dark:text-slate-200",
              open && isExplicitModel && "text-violet-700 dark:text-violet-100",
            )}
            aria-hidden="true"
          />
        </button>
      </div>
      {menu && typeof document !== "undefined" ? createPortal(menu, document.body) : null}
    </>
  );
}

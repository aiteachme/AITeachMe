import {
  useState,
  useEffect,
  useLayoutEffect,
  useRef,
  type ChangeEvent,
  type ClipboardEventHandler,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { motion } from "framer-motion";
import { ArrowUp, Plus, Square } from "lucide-react";
import { cn } from "../../lib/utils";
import { ChatModelSelect, type ChatModelChoice } from "./ChatModelSelect";
import { FileDropOverlay, useFileDropZone } from "../ui/FileDropZone";

interface ChatComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  onAbort: () => void;
  isStreaming: boolean;
  disabled?: boolean;
  autoFocusKey?: number;
  placeholder?: string;
  modelValue?: ChatModelChoice;
  onModelChange?: (value: ChatModelChoice) => void;
  layout?: "dock" | "home";
  canSend?: boolean;
  homeAttachmentContent?: ReactNode;
  homeToolbarActions?: ReactNode;
  homeHighlighted?: boolean;
  onPaste?: ClipboardEventHandler<HTMLTextAreaElement>;
  onFilesDrop?: (files: File[]) => void;
}

const TEXTAREA_MIN_HEIGHT = 32;
const TEXTAREA_MAX_HEIGHT = 160;
const HOME_TEXTAREA_MIN_HEIGHT = 104;
const HOME_TEXTAREA_MAX_HEIGHT = 240;
const COMPOSER_LAYOUT_TRANSITION = {
  type: "spring",
  stiffness: 520,
  damping: 42,
  mass: 0.7,
} as const;

export function ChatComposer({
  value,
  onChange,
  onSend,
  onAbort,
  isStreaming,
  disabled = false,
  autoFocusKey,
  placeholder = "问我一个问题，或者让我结合资料解释某个概念...",
  modelValue,
  onModelChange,
  layout = "dock",
  canSend,
  homeAttachmentContent,
  homeToolbarActions,
  homeHighlighted = false,
  onPaste,
  onFilesDrop,
}: ChatComposerProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isDockMultiline, setIsDockMultiline] = useState(false);
  const shouldShowModelSelect = Boolean(modelValue && onModelChange);
  const textareaMinHeight = layout === "home" ? HOME_TEXTAREA_MIN_HEIGHT : TEXTAREA_MIN_HEIGHT;
  const textareaMaxHeight = layout === "home" ? HOME_TEXTAREA_MAX_HEIGHT : TEXTAREA_MAX_HEIGHT;
  const canSubmit = canSend ?? Boolean(value.trim());
  const canAttachFiles = Boolean(onFilesDrop) && !disabled && !isStreaming;
  const { isDragActive: isFileDragActive, dropZoneHandlers: fileDropHandlers } = useFileDropZone<HTMLDivElement>({
    disabled: disabled || isStreaming,
    onDropFiles: onFilesDrop,
  });

  useLayoutEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) {
      return;
    }

    textarea.style.height = `${textareaMinHeight}px`;
    textarea.style.overflowY = "hidden";

    let nextHeight = textareaMinHeight;
    if (value.length > 0) {
      nextHeight = Math.min(
        Math.max(textarea.scrollHeight, textareaMinHeight),
        textareaMaxHeight,
      );
      textarea.style.height = `${nextHeight}px`;
      textarea.style.overflowY = textarea.scrollHeight > textareaMaxHeight ? "auto" : "hidden";
    }

    if (layout === "dock") {
      const nextIsMultiline = Boolean(value) && (
        value.includes("\n") || nextHeight > TEXTAREA_MIN_HEIGHT + 8
      );
      setIsDockMultiline((current) => (current === nextIsMultiline ? current : nextIsMultiline));
    }
  }, [autoFocusKey, layout, placeholder, textareaMaxHeight, textareaMinHeight, value]);

  useEffect(() => {
    if (autoFocusKey === undefined) {
      return;
    }
    textareaRef.current?.focus({ preventScroll: true });
  }, [autoFocusKey]);

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !isStreaming && canSubmit && !disabled) {
      event.preventDefault();
      onSend();
    }
  }

  function handlePickFiles() {
    if (!canAttachFiles) {
      return;
    }
    fileInputRef.current?.click();
  }

  function handleFileInputChange(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.currentTarget.files ?? []);
    if (files.length > 0) {
      onFilesDrop?.(files);
    }
    event.currentTarget.value = "";
  }

  const fileDropOverlay = isFileDragActive ? <FileDropOverlay /> : null;

  const actionButton = isStreaming ? (
    <button
      type="button"
      onClick={onAbort}
      aria-label="停止生成"
      title="停止生成"
      className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-zinc-100 text-zinc-950 shadow-sm transition-all hover:bg-zinc-200 focus:outline-none focus:ring-4 focus:ring-zinc-900/10 active:scale-[0.98] dark:bg-slate-100 dark:text-slate-950 dark:hover:bg-white dark:focus:ring-slate-100/10"
    >
      <Square className="h-3.5 w-3.5 fill-current stroke-0" />
    </button>
  ) : (
    <button
      type="button"
      onClick={onSend}
      disabled={!canSubmit || disabled}
      className={cn(
        "inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-[14px] font-medium transition-all active:scale-[0.95] focus:outline-none focus:ring-4 focus:ring-zinc-900/10",
        canSubmit && !disabled
          ? "bg-zinc-900 text-white shadow-sm hover:bg-zinc-800 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-white"
          : "cursor-not-allowed bg-zinc-100 text-zinc-300 dark:bg-slate-800 dark:text-slate-600",
      )}
    >
      <ArrowUp className="h-4 w-4" />
    </button>
  );

  const attachmentButton = (
    <button
      type="button"
      onClick={handlePickFiles}
      disabled={!canAttachFiles}
      aria-label="添加资料"
      title={canAttachFiles ? "添加资料" : "当前不可添加资料"}
      className={cn(
        "inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-zinc-700 transition focus:outline-none focus:ring-2 focus:ring-zinc-900/10 dark:text-slate-200 dark:focus:ring-slate-100/10",
        canAttachFiles
          ? "hover:bg-zinc-100 active:scale-[0.97] dark:hover:bg-slate-800"
          : "cursor-default",
      )}
    >
      <Plus className="h-5 w-5" />
    </button>
  );

  if (layout === "home") {
    const homeActionButton = isStreaming ? (
      <button
        type="button"
        onClick={onAbort}
        aria-label="停止生成"
        title="停止生成"
        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-zinc-100 text-zinc-950 shadow-sm transition-all hover:bg-zinc-200 focus:outline-none focus:ring-4 focus:ring-zinc-900/10 active:scale-[0.98] dark:bg-slate-100 dark:text-slate-950 dark:hover:bg-white dark:focus:ring-slate-100/10"
      >
        <Square className="h-3.5 w-3.5 fill-current stroke-0" />
      </button>
    ) : (
      <button
        type="button"
        onClick={onSend}
        disabled={!canSubmit || disabled}
        className={cn(
          "flex h-9 w-9 shrink-0 items-center justify-center rounded-full transition-all focus:outline-none focus:ring-4 focus:ring-zinc-900/10 active:scale-[0.98]",
          canSubmit && !disabled
            ? "bg-zinc-900 text-white shadow-sm hover:bg-zinc-800 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-white"
            : "cursor-not-allowed bg-zinc-100 text-zinc-300 dark:bg-slate-800 dark:text-slate-600",
        )}
      >
        <ArrowUp className="h-4 w-4" />
      </button>
    );

    return (
      <div className="w-full bg-transparent">
        <div className="mx-auto w-full max-w-[800px]">
          <div
            {...fileDropHandlers}
            className={cn(
              "relative w-full overflow-hidden rounded-[30px] border-[1.5px] border-zinc-200/80 bg-white/70 shadow-[0_6px_20px_rgba(0,0,0,0.035)] backdrop-blur-xl transition-all hover:border-zinc-300 hover:bg-white/80 hover:shadow-[0_8px_24px_rgba(0,0,0,0.055)] focus-within:border-indigo-300 focus-within:shadow-[0_8px_26px_rgba(99,102,241,0.10)] focus-within:ring-4 focus-within:ring-indigo-500/10 dark:border-slate-700 dark:bg-slate-900/70 dark:hover:border-slate-600 dark:hover:bg-slate-900/90 dark:focus-within:border-indigo-500/50",
              (value.trim() || homeHighlighted) && "border-indigo-300/80 bg-indigo-50/40 shadow-[0_8px_24px_rgba(99,102,241,0.08)] ring-2 ring-indigo-500/8 dark:border-indigo-500/30 dark:bg-indigo-900/10 dark:shadow-[0_8px_24px_rgba(99,102,241,0.14)]",
              isFileDragActive && "border-zinc-900 bg-white ring-4 ring-zinc-900/10 dark:border-slate-100 dark:bg-slate-900 dark:ring-slate-100/10",
            )}
          >
            {fileDropOverlay}
            <textarea
              ref={textareaRef}
              rows={3}
              value={value}
              onChange={(event) => onChange(event.target.value)}
              onKeyDown={handleKeyDown}
              onPaste={onPaste}
              disabled={disabled}
              placeholder={placeholder}
              className="w-full min-h-[104px] max-h-[240px] resize-none border-0 bg-transparent px-3 pb-1.5 pt-3 text-base leading-7 text-zinc-800 outline-none placeholder:text-zinc-400 disabled:cursor-not-allowed disabled:opacity-60 dark:text-slate-200 dark:placeholder:text-slate-500"
            />

            <div className="flex flex-col gap-2 px-3 pb-2.5 pt-0.5">
              {homeAttachmentContent}
              <div className="flex flex-col gap-2 px-1 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex min-w-0 w-full flex-wrap items-center gap-1.5 sm:flex-1 sm:gap-2">
                  {homeToolbarActions}
                </div>
                <div className="flex w-full items-center justify-between gap-2 sm:w-auto sm:shrink-0 sm:justify-end">
                  {shouldShowModelSelect ? (
                    <ChatModelSelect
                      value={modelValue!}
                      onChange={onModelChange!}
                      disabled={disabled || isStreaming}
                      className="shrink-0"
                    />
                  ) : <span />}
                  {homeActionButton}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="w-full bg-gradient-to-t from-white via-white to-white/80 px-4 pb-5 pt-3 dark:from-slate-950 dark:via-slate-950 dark:to-slate-950/80 md:px-8">
      <div className="mx-auto w-full max-w-3xl xl:max-w-4xl 2xl:max-w-5xl">
        <div
          {...fileDropHandlers}
          style={{ borderRadius: 26 }}
          className={cn(
            "relative overflow-hidden border border-zinc-200/80 bg-white/95 backdrop-blur-xl shadow-[0_6px_18px_-12px_rgba(0,0,0,0.24),0_10px_28px_-22px_rgba(0,0,0,0.22)] transition-[border-color,box-shadow,background-color] duration-200 ease-out focus-within:border-zinc-300 focus-within:bg-white focus-within:shadow-[0_8px_22px_-14px_rgba(0,0,0,0.22),0_14px_34px_-26px_rgba(0,0,0,0.20)] dark:border-slate-800/80 dark:bg-slate-950/92 dark:shadow-[0_12px_28px_-22px_rgba(0,0,0,0.70)] dark:focus-within:border-slate-700 dark:focus-within:bg-slate-950",
            isFileDragActive && "border-zinc-900 bg-white ring-4 ring-zinc-900/10 dark:border-slate-100 dark:bg-slate-950 dark:ring-slate-100/10",
          )}
        >
          {fileDropOverlay}
          {onFilesDrop ? (
            <input
              ref={fileInputRef}
              type="file"
              multiple
              className="hidden"
              onChange={handleFileInputChange}
              tabIndex={-1}
            />
          ) : null}

          <motion.div
            layout
            transition={COMPOSER_LAYOUT_TRANSITION}
            className={cn(
              "grid min-h-[52px] grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-x-1.5 px-2 py-1 transition-[gap,padding] duration-200 ease-out motion-reduce:transition-none",
              isDockMultiline && "items-end gap-y-2 px-3 pb-2.5 pt-3",
            )}
          >
            <motion.div
              layout
              transition={COMPOSER_LAYOUT_TRANSITION}
              className={cn("col-start-1 row-start-1", isDockMultiline && "row-start-2")}
            >
              {attachmentButton}
            </motion.div>

            <textarea
              ref={textareaRef}
              rows={1}
              value={value}
              onChange={(event) => onChange(event.target.value)}
              onKeyDown={handleKeyDown}
              disabled={disabled}
              placeholder={placeholder}
              className={cn(
                "row-start-1 max-h-40 min-h-8 resize-none overflow-y-hidden bg-transparent px-1 text-[15px] leading-6 text-zinc-800 outline-none transition-[height,padding] duration-200 ease-out placeholder:text-zinc-400 motion-reduce:transition-none disabled:cursor-not-allowed disabled:opacity-60 dark:text-slate-100 dark:placeholder:text-slate-500",
                isDockMultiline
                  ? "col-span-3 col-start-1 w-full py-0.5"
                  : "col-start-2 h-8 w-full py-1",
              )}
              style={{ maxHeight: `${textareaMaxHeight}px` }}
            />

            <motion.div
              layout
              transition={COMPOSER_LAYOUT_TRANSITION}
              className={cn("col-start-3 row-start-1 flex shrink-0 items-center gap-1.5", isDockMultiline && "row-start-2")}
            >
              {shouldShowModelSelect ? (
                <ChatModelSelect
                  value={modelValue!}
                  onChange={onModelChange!}
                  disabled={disabled || isStreaming}
                  className="shrink-0"
                />
              ) : null}
              {actionButton}
            </motion.div>
          </motion.div>
        </div>
      </div>
    </div>
  );
}

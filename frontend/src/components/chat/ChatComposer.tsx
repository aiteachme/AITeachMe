import { useEffect, useRef } from "react";
import { Loader2, Send, Square } from "lucide-react";
import { cn } from "../../lib/utils";

interface ChatComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  onAbort: () => void;
  isStreaming: boolean;
  disabled?: boolean;
}

export function ChatComposer({
  value,
  onChange,
  onSend,
  onAbort,
  isStreaming,
  disabled = false,
}: ChatComposerProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!textareaRef.current) {
      return;
    }
    textareaRef.current.style.height = "auto";
    textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 200)}px`;
  }, [value]);

  function handleKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !isStreaming) {
      event.preventDefault();
      onSend();
    }
  }

  return (
    <div className="absolute bottom-6 left-1/2 w-full max-w-3xl -translate-x-1/2 px-4 z-20">
      <div className="mx-auto w-full">
        <div className="rounded-2xl border border-zinc-200/80 bg-white/95 backdrop-blur-xl shadow-[0_8px_24px_-8px_rgba(0,0,0,0.12),0_16px_48px_-16px_rgba(0,0,0,0.12)] transition-all focus-within:border-zinc-300 focus-within:shadow-[0_12px_32px_-12px_rgba(0,0,0,0.16),0_24px_64px_-20px_rgba(0,0,0,0.16)] focus-within:bg-white">
          <div className="flex items-end gap-3 px-3 py-2.5">
            <textarea
              ref={textareaRef}
              rows={1}
              value={value}
              onChange={(event) => onChange(event.target.value)}
              onKeyDown={handleKeyDown}
              disabled={disabled}
              placeholder="问我一个问题，或者让我结合资料解释某个概念..."
              className="min-h-[48px] flex-1 resize-none bg-transparent px-3 py-3 text-[14px] leading-relaxed text-zinc-800 outline-none placeholder:text-zinc-400 disabled:cursor-not-allowed disabled:opacity-60"
              style={{ maxHeight: "200px" }}
            />

            {isStreaming ? (
              <button
                type="button"
                onClick={onAbort}
                className="inline-flex h-10 shrink-0 items-center justify-center gap-1.5 rounded-xl bg-zinc-800 px-3.5 text-[13px] font-medium text-white transition hover:bg-zinc-700 focus:outline-none focus:ring-4 focus:ring-zinc-900/10 active:scale-[0.98]"
              >
                <Square className="h-3.5 w-3.5 fill-current" />
                停止
              </button>
            ) : (
              <button
                type="button"
                onClick={onSend}
                disabled={!value.trim() || disabled}
                className={cn(
                  "inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-[14px] font-medium transition-all active:scale-[0.95] focus:outline-none focus:ring-4 focus:ring-zinc-900/10",
                  value.trim() && !disabled
                    ? "bg-zinc-900 text-white shadow-sm hover:bg-zinc-800"
                    : "cursor-not-allowed bg-zinc-100 text-zinc-300",
                )}
              >
                <Send className="h-4 w-4 ml-0.5" />
              </button>
            )}
          </div>
        </div>

        <div className="mt-2.5 flex items-center justify-between gap-3 px-2 text-[11px] font-medium tracking-wide text-zinc-400">
          <span className="hidden sm:inline-block">Enter 发送，Shift + Enter 换行</span>
          <span className="inline-flex items-center gap-1.5 ml-auto">
            {isStreaming ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
            AI 可能会出错，请核实关键结论
          </span>
        </div>
      </div>
    </div>
  );
}

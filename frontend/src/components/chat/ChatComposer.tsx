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
    <div className="absolute bottom-8 left-1/2 w-full max-w-4xl -translate-x-1/2 px-4 z-20">
      <div className="mx-auto w-full">
        <div className="rounded-[32px] border border-slate-200/80 bg-white/75 backdrop-blur-2xl shadow-[0_20px_60px_-15px_rgba(15,23,42,0.15)] transition-all focus-within:border-sky-300 focus-within:bg-white/95">
          <div className="flex items-end gap-3 px-4 py-3">
            <textarea
              ref={textareaRef}
              rows={1}
              value={value}
              onChange={(event) => onChange(event.target.value)}
              onKeyDown={handleKeyDown}
              disabled={disabled}
              placeholder="问我一个问题，或者让我结合资料解释某个概念..."
              className="min-h-[52px] flex-1 resize-none bg-transparent px-2 py-3 text-[15px] leading-7 text-slate-800 outline-none placeholder:text-slate-400 disabled:cursor-not-allowed disabled:opacity-60"
              style={{ maxHeight: "200px" }}
            />

            {isStreaming ? (
              <button
                type="button"
                onClick={onAbort}
                className="inline-flex h-11 items-center justify-center gap-2 rounded-2xl bg-rose-600 px-4 text-sm font-medium text-white transition hover:bg-rose-500"
              >
                <Square className="h-4 w-4 fill-current" />
                停止
              </button>
            ) : (
              <button
                type="button"
                onClick={onSend}
                disabled={!value.trim() || disabled}
                className={cn(
                  "inline-flex h-[42px] w-[42px] shrink-0 items-center justify-center rounded-[18px] text-sm font-medium transition-all active:scale-95",
                  value.trim() && !disabled
                    ? "bg-slate-900 text-white shadow-md shadow-slate-900/10 hover:bg-slate-800"
                    : "cursor-not-allowed bg-slate-100 text-slate-300",
                )}
              >
                <Send className="h-4 w-4 ml-0.5" />
              </button>
            )}
          </div>
        </div>

        <div className="mt-3 flex items-center justify-between gap-3 px-2 text-[11px] font-medium text-slate-400">
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

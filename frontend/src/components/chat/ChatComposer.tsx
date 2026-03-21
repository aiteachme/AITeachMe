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
    <div className="border-t border-slate-200/80 bg-white/90 px-4 py-4 backdrop-blur xl:px-8">
      <div className="mx-auto max-w-4xl">
        <div className="rounded-[28px] border border-slate-200 bg-white shadow-[0_12px_40px_-24px_rgba(15,23,42,0.45)] transition focus-within:border-sky-300">
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
                  "inline-flex h-11 items-center justify-center rounded-2xl px-4 text-sm font-medium transition",
                  value.trim() && !disabled
                    ? "bg-slate-900 text-white shadow-sm hover:bg-slate-800"
                    : "cursor-not-allowed bg-slate-100 text-slate-300",
                )}
              >
                <Send className="h-4 w-4" />
              </button>
            )}
          </div>
        </div>

        <div className="mt-3 flex items-center justify-between gap-3 px-1 text-xs text-slate-400">
          <span>Enter 发送，Shift + Enter 换行</span>
          <span className="inline-flex items-center gap-2">
            {isStreaming ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
            AI 可能会出错，请核实关键结论
          </span>
        </div>
      </div>
    </div>
  );
}
